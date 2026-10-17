// Durable local outbox. Firebase writes are idempotent: retries use the same path.
export class LocalQueue {
  constructor(db){this.db=db;}
  static open(){return new Promise((resolve,reject)=>{
    const r=indexedDB.open('roadmonitor-cloud-v1',1);
    r.onupgradeneeded=()=>{r.result.createObjectStore('outbox',{keyPath:'path'});r.result.createObjectStore('active',{keyPath:'sid'});};
    r.onsuccess=()=>resolve(new LocalQueue(r.result));r.onerror=()=>reject(r.error);
    r.onblocked=()=>reject(Error('Close other RoadMonitor tabs and retry.'));
  });}
  all(store='outbox'){return new Promise((resolve,reject)=>{const r=this.db.transaction(store).objectStore(store).getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  change(rows=[],remove=[],marker=null,removeMarker=null){return new Promise((resolve,reject)=>{
    const tx=this.db.transaction(['outbox','active'],'readwrite'),q=tx.objectStore('outbox');
    rows.forEach(row=>q.put(row));remove.forEach(path=>q.delete(path));
    if(marker)tx.objectStore('active').put(marker);if(removeMarker)tx.objectStore('active').delete(removeMarker);
    tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Local storage transaction aborted'));
  });}
  acknowledge(row){return new Promise((resolve,reject)=>{
    const tx=this.db.transaction('outbox','readwrite'),s=tx.objectStore('outbox'),r=s.get(row.path);
    r.onsuccess=()=>{if(r.result?.rev===row.rev)s.delete(row.path);};
    tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
  });}
}
export class Recorder {
  constructor(queue,writeDoc,onState=()=>{}){this.q=queue;this.writeDoc=writeDoc;this.onState=onState;this.active=null;this.chain=Promise.resolve();this.syncing=false;this.lastError='';this.localError='';this.received=0;this.lastUpload=null;}
  row(path,uid,payload,ready=true){return {path,uid,payload,ready,rev:crypto.randomUUID(),queuedAt:Date.now()};}
  schedule(fn){const result=this.chain.then(fn);this.chain=result.catch(e=>{this.active=null;this.localError='LOCAL SAVE FAILED: '+e.message+'. Recording stopped; some readings may not have been saved.';this.onState();});return result;}
  async recover(uid){
    await this.chain;
    const markers=(await this.q.all('active')).filter(m=>m.uid===uid);
    const rows=await this.q.all();
    for(const m of markers){
      const sealed=rows.filter(r=>r.uid===uid&&r.payload.sessionId===m.sid&&!r.ready).map(r=>({...r,ready:true,rev:crypto.randomUUID()}));
      const manifest=this.row(m.path,uid,{...m.manifest,status:'interrupted',endedAtMs:null,interruptedDetectedAtMs:Date.now()});
      await this.q.change([...sealed,manifest],[],null,m.sid);
    }
    this.onState();
  }
  async start(uid,name,simulated,settings){
    if(this.active)throw Error('Already recording');
    await this.chain;
    const sid=crypto.randomUUID(),path=`users/${uid}/sessions/${sid}`,startedAtMs=Date.now();
    const manifest={schema:1,name:name.trim().slice(0,100)||'Road survey',startedAtMs,endedAtMs:null,status:'recording',simulated,device:'RoadMonitor-S3',settings,ice:'not_measured'};
    await this.q.change([this.row(path,uid,manifest)],[],{sid,uid,path,manifest});
    this.active={uid,sid,path,manifest,index:0,chunk:null};this.received=0;this.lastError='';this.onState();return sid;
  }
  capture(record){
    const session=this.active;if(!session)return Promise.resolve();
    this.received++;
    return this.schedule(async()=>{
      const now=Date.now();
      if(session.chunk && (now-session.chunk.payload.startedAtMs>=5000 || session.chunk.payload.records.length>=100)){
        session.chunk.ready=true;session.chunk.rev=crypto.randomUUID();await this.q.change([session.chunk]);session.chunk=null;
      }
      if(!session.chunk){session.chunk=this.row(`${session.path}/chunks/${String(session.index).padStart(8,'0')}`,session.uid,{schema:1,sessionId:session.sid,index:session.index++,startedAtMs:record.receivedAtMs,records:[]},false);}
      session.chunk.payload.records.push(record);session.chunk.payload.endedAtMs=record.receivedAtMs;session.chunk.rev=crypto.randomUUID();
      await this.q.change([session.chunk]);
    });
  }
  seal(){const session=this.active;if(!session)return this.chain;return this.schedule(async()=>{if(session.chunk){session.chunk.ready=true;session.chunk.rev=crypto.randomUUID();await this.q.change([session.chunk]);session.chunk=null;}});}
  stop(reason='stopped'){
    const session=this.active;if(!session)return this.chain;this.active=null;this.onState();
    return this.schedule(async()=>{
      const rows=[];if(session.chunk){session.chunk.ready=true;session.chunk.rev=crypto.randomUUID();rows.push(session.chunk);}
      rows.push(this.row(session.path,session.uid,{...session.manifest,status:reason,endedAtMs:Date.now(),receivedRecords:this.received}));
      await this.q.change(rows,[],null,session.sid);this.onState();
    });
  }
  async sync(uid){
    if(this.syncing||!uid)return;this.syncing=true;this.onState();
    try{
      // A bounded snapshot keeps syncing from starving the recording queue.
      const rows=(await this.q.all()).filter(r=>r.uid===uid&&r.ready).sort((a,b)=>a.queuedAt-b.queuedAt).slice(0,150);
      for(const row of rows){await this.writeDoc(row.path,row.payload);await this.q.acknowledge(row);this.lastUpload=Date.now();}
      this.lastError='';
    }catch(e){this.lastError=e.code?`${e.code}: ${e.message}`:e.message;}
    finally{this.syncing=false;this.onState();}
  }
}
