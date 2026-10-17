import {firebaseConfig} from './firebase-config.js';
import {LocalQueue,Recorder} from './recorder.js';
const el=id=>document.getElementById(id),say=(id,text)=>{el(id).textContent=text;};
let sdk=null,auth=null,db=null,queue=null,recorder=null,user=null,ready=false,lockTaken=false,working=false;
let tripCursor=null,tripDocs=[],chunkCursor=null,selected=null,history=[],gpsBefore=[],sensorBefore=[],playTimer=null,loadGeneration=0;
const SDK='https://www.gstatic.com/firebasejs/12.19.0/';
const hints={
 'auth/unauthorized-domain':'Add localhost under Firebase Authentication → Settings → Authorized domains.',
 'auth/operation-not-allowed':'Enable Google in Firebase Authentication → Sign-in method.',
 'auth/popup-blocked':'Allow the sign-in popup, then click Sign in again.',
 'auth/popup-closed-by-user':'Sign-in was cancelled. Click Sign in again when ready.',
 'auth/api-key-not-valid.-please-pass-a-valid-api-key.':'Check apiKey in firebase-config.js against Firebase → Project settings → General → Config.',
 'permission-denied':'Publish the included firestore.rules in Firestore Database → Rules. Make sure this is Firestore, not Realtime Database.',
 'not-found':'Create the default Cloud Firestore database for roadmonitor-16c51.',
 'resource-exhausted':'Firebase quota reached. Readings remain queued on this Mac; retry after quota resets or review your Firebase plan.'
};
function errorText(e){return `${e.code||'Error'}: ${hints[e.code]||e.message}`;}
async function takeLock(){
 if(lockTaken)return;if(!navigator.locks)throw Error('Cloud recording needs Chrome on localhost with Web Locks support.');
 await new Promise((resolve,reject)=>{navigator.locks.request('roadmonitor-cloud-writer',{ifAvailable:true},async lock=>{if(!lock){reject(Error('Cloud is open in another RoadMonitor tab. Close that tab and retry.'));return;}lockTaken=true;resolve();await new Promise(()=>{});}).catch(reject);});
}
function buttons(){
 const source=window.roadMonitor.status();
 el('googleSignIn').disabled=!ready||!!user||working;
 el('googleSignOut').disabled=!user||!!recorder?.active||working||recorder?.syncing;
 el('recordStart').disabled=!user||working||!!recorder?.active||!!recorder?.localError||!source.fresh||(!source.live&&!source.simulated);
 el('recordStop').disabled=!recorder?.active||working;
 for(const id of ['syncNow','listTrips'])el(id).disabled=!user||working;
 el('tripName').disabled=!!recorder?.active;
}
async function state(){
 buttons();if(!queue||!recorder||!user)return;
 const uid=user.uid;
 try{
  const rows=(await queue.all()).filter(r=>r.uid===uid);if(user?.uid!==uid)return;
  const samples=rows.reduce((sum,r)=>sum+(r.payload.records?.length||0),0);
  const status=recorder.active?`${recorder.active.manifest.simulated?'SIMULATION · ':''}Recording “${recorder.active.manifest.name}” · ${recorder.received} readings received.`:'Not recording.';
  const saved=rows.length?`${samples} readings / ${rows.length} documents saved locally, awaiting cloud confirmation.`:'All uploaded. No locally queued documents for this account.';
  say('cloudStatus',`${status}\n${recorder.syncing?'Uploading… ':''}${saved}${recorder.lastUpload?' Last confirmation: '+new Date(recorder.lastUpload).toLocaleTimeString()+'.':''}${recorder.localError?'\n'+recorder.localError:''}${recorder.lastError?'\nUpload issue: '+recorder.lastError:''}${!navigator.onLine?'\nMac is offline. Keep recording here; uploads resume when internet returns.':''}`);
 }catch(e){say('cloudStatus','Cannot read local save queue: '+e.message);}
}
async function enable(){
 el('enableCloud').disabled=true;say('cloudStatus','Loading Firebase… Your live BLE dashboard continues to work.');
 try{
  await takeLock();queue=await LocalQueue.open();
  const [appModule,authModule,firestoreModule]=await Promise.all([import(SDK+'firebase-app.js'),import(SDK+'firebase-auth.js'),import(SDK+'firebase-firestore.js')]);
  sdk={...authModule,...firestoreModule};const app=appModule.initializeApp(firebaseConfig);auth=sdk.getAuth(app);db=sdk.getFirestore(app);
  recorder=new Recorder(queue,async(path,data)=>{if(auth.currentUser?.uid!==path.split('/')[1])throw Error('Sign in with the account that recorded these readings to resume uploading.');await sdk.setDoc(sdk.doc(db,path),data);},()=>{state();});
  ready=true;el('enableCloud').textContent='Cloud enabled';say('cloudStatus','Sign in with Google, connect your sensor, then click Start recording.');
  sdk.onAuthStateChanged(auth,async next=>{
   loadGeneration++;stopPlayback();clearHistory();
   if(recorder.active)await recorder.stop('account-changed').catch(()=>{});
   user=next;tripDocs=[];tripCursor=null;el('tripSelect').replaceChildren(new Option(next?'Click Find trips':'Sign in to view saved trips',''));el('tripSelect').disabled=true;el('loadTrip').disabled=true;el('moreTrips').disabled=true;
   say('cloudAccount',next?(next.email||'Signed in'):'Signed out');
   if(next){working=true;buttons();try{await recorder.recover(next.uid);await state();void recorder.sync(next.uid);}catch(e){say('cloudStatus',errorText(e));}finally{working=false;buttons();}}
   else{say('cloudStatus','Sign in with Google to record or review trips. Existing local uploads stay on this Mac until their owner signs in.');buttons();}
  });
  setInterval(async()=>{if(!user)return;await recorder.seal().catch(()=>{});void recorder.sync(user.uid);},5000);
 }catch(e){say('cloudStatus','Cloud could not start: '+errorText(e)+'. Check internet, then retry. BLE remains available.');el('enableCloud').disabled=false;}
 buttons();
}
el('enableCloud').onclick=enable;
el('googleSignIn').onclick=async()=>{try{const p=new sdk.GoogleAuthProvider();p.setCustomParameters({prompt:'select_account'});await sdk.signInWithPopup(auth,p);}catch(e){say('cloudStatus',errorText(e));}};
el('googleSignOut').onclick=async()=>{try{await sdk.signOut(auth);}catch(e){say('cloudStatus',errorText(e));}};
el('recordStart').onclick=async()=>{
 if(working||!user||recorder.active)return;working=true;buttons();
 try{const source=window.roadMonitor.status();if(!source.fresh)throw Error('Connect the board or start simulation and wait for readings.');await recorder.start(user.uid,el('tripName').value,source.simulated,window.roadMonitor.settings());await state();void recorder.sync(user.uid);}
 catch(e){say('cloudStatus',errorText(e));}finally{working=false;buttons();}
};
async function stop(reason='stopped'){if(!recorder?.active)return;working=true;buttons();try{await recorder.stop(reason);await state();if(user)void recorder.sync(user.uid);}catch(e){say('cloudStatus',errorText(e));}finally{working=false;buttons();}}
el('recordStop').onclick=()=>stop();
el('syncNow').onclick=async()=>{if(!user)return;await recorder.seal().catch(()=>{});void recorder.sync(user.uid);};
window.addEventListener('roadmonitor:reading',e=>{if(recorder?.active){if(recorder.active.manifest.simulated!==e.detail.simulated){void stop('source-changed');return;}void recorder.capture(e.detail).catch(()=>{});}});
window.addEventListener('roadmonitor:ended',e=>{void stop(e.detail);});
window.addEventListener('online',()=>{if(user&&recorder)void recorder.sync(user.uid);});
window.addEventListener('beforeunload',e=>{if(recorder?.active||recorder?.syncing){e.preventDefault();e.returnValue='';}});
setInterval(()=>{buttons();if(user)void state();},1000);

// History is read on demand from the server. No always-on database listeners.
async function listTrips(more=false){
 if(!user)return;const uid=user.uid,generation=++loadGeneration;working=true;buttons();
 try{
  const from=el('historyFrom').value,to=el('historyTo').value;
  if(from&&to&&from>to)throw Error('The From date must be on or before the Through date.');
  const filters=[];if(from)filters.push(sdk.where('startedAtMs','>=',new Date(from+'T00:00:00').getTime()));
  if(to){const end=new Date(to+'T00:00:00');end.setDate(end.getDate()+1);filters.push(sdk.where('startedAtMs','<',end.getTime()));}
  filters.push(sdk.orderBy('startedAtMs','desc'));if(more&&tripCursor)filters.push(sdk.startAfter(tripCursor));filters.push(sdk.limit(25));
  say('historyStatus','Loading saved trips…');
  const result=await sdk.getDocsFromServer(sdk.query(sdk.collection(db,'users',uid,'sessions'),...filters));
  if(user?.uid!==uid||generation!==loadGeneration)return;
  if(!more)tripDocs=[];tripDocs.push(...result.docs);tripCursor=result.docs.at(-1)||null;
  el('tripSelect').replaceChildren();
  tripDocs.forEach(d=>{const s=d.data();el('tripSelect').add(new Option(`${s.simulated?'[SIM] ':''}${new Date(s.startedAtMs).toLocaleString()} · ${s.name} · ${s.status}`,d.id));});
  if(!tripDocs.length)el('tripSelect').add(new Option('No saved trips in this date range',''));
  el('tripSelect').disabled=!tripDocs.length;el('loadTrip').disabled=!tripDocs.length;el('moreTrips').disabled=result.size<25;
  say('historyStatus',`${tripDocs.length} trips listed. Open one to view its saved readings. Dates filter by trip start time on this Mac.`);
 }catch(e){say('historyStatus',errorText(e));}finally{working=false;buttons();}
}
el('listTrips').onclick=()=>listTrips();el('moreTrips').onclick=()=>listTrips(true);
for(const id of ['historyFrom','historyTo'])el(id).onchange=()=>{tripCursor=null;el('moreTrips').disabled=true;};
function clearHistory(){history=[];gpsBefore=[];sensorBefore=[];selected=null;chunkCursor=null;el('playback').hidden=true;el('nextPart').disabled=true;el('downloadPart').disabled=true;say('historyStatus','Find a trip to view historical readings.');}
async function loadPart(next=false){
 if(!user)return;const uid=user.uid,generation=++loadGeneration;working=true;buttons();stopPlayback();
 try{
  if(!next){selected=tripDocs.find(d=>d.id===el('tripSelect').value);chunkCursor=null;}
  if(!selected)throw Error('Choose a trip first.');
  const chosen=selected;
  say('historyStatus','Loading a portion of the recording…');el('nextPart').disabled=true;el('loadTrip').disabled=true;
  const constraints=[sdk.orderBy('index')];if(next&&chunkCursor)constraints.push(sdk.startAfter(chunkCursor));constraints.push(sdk.limit(100));
  const result=await sdk.getDocsFromServer(sdk.query(sdk.collection(db,'users',uid,'sessions',chosen.id,'chunks'),...constraints));
  if(user?.uid!==uid||generation!==loadGeneration)return;
  chunkCursor=result.docs.at(-1)||null;history=result.docs.flatMap(d=>d.data().records||[]);el('nextPart').disabled=result.size<100;el('downloadPart').disabled=!history.length;
  let s=null,g=null;sensorBefore=[];gpsBefore=[];
  history.forEach((r,i)=>{if(r.data?.type===1)s={...r.data,at:r.receivedAtMs,assessment:r.assessment};if(r.data?.type===2)g={...r.data,at:r.receivedAtMs};sensorBefore[i]=s;gpsBefore[i]=g;});
  el('historySlider').max=Math.max(0,history.length-1);el('historySlider').value=0;el('playback').hidden=!history.length;
  const m=chosen.data();say('historyStatus',`${m.simulated?'SIMULATED · ':''}${m.name} · ${history.length} readings in this portion${history.length?' · '+new Date(history[0].receivedAtMs).toLocaleString()+' – '+new Date(history.at(-1).receivedAtMs).toLocaleTimeString():'. No uploaded readings yet.'}${result.size===100?' · Use Next portion to continue.':''} · Trip status: ${m.status}.`);
  showFrame();
 }catch(e){say('historyStatus',errorText(e));}finally{working=false;buttons();el('loadTrip').disabled=!user||!tripDocs.length;}
}
el('loadTrip').onclick=()=>loadPart();el('nextPart').onclick=()=>loadPart(true);
el('tripSelect').onchange=()=>{stopPlayback();clearHistory();};
function stopPlayback(){if(playTimer)clearInterval(playTimer);playTimer=null;el('playTrip').textContent='Play';}
el('playTrip').onclick=()=>{
 if(playTimer){stopPlayback();return;}if(!history.length)return;
 if(Number(el('historySlider').value)>=history.length-1)el('historySlider').value=0;
 const baseIndex=Number(el('historySlider').value),baseTime=history[baseIndex].receivedAtMs,start=performance.now();el('playTrip').textContent='Pause';
 playTimer=setInterval(()=>{let i=Number(el('historySlider').value);const now=baseTime+(performance.now()-start);while(i+1<history.length&&history[i+1].receivedAtMs<=now)i++;el('historySlider').value=i;showFrame();if(i>=history.length-1)stopPlayback();},80);
};
el('historySlider').oninput=()=>{stopPlayback();showFrame();};
function showFrame(){
 if(!history.length)return;const i=Number(el('historySlider').value),r=history[i];let s=sensorBefore[i],g=gpsBefore[i];
 if(s&&r.receivedAtMs-s.at>2000)s=null;if(g&&r.receivedAtMs-g.at>3000)g=null;
 say('historyTime',new Date(r.receivedAtMs).toLocaleString());
 const values=[['Observation',s?.assessment?.title||'No fresh sensor reading'],['Ground distance',s?.rangeValid&&s.distance!==null?(s.distance/10).toFixed(1)+' cm':'Unavailable'],['Vibration',s?.accelValid&&s.accelCal&&s.vibration!==null?s.vibration.toFixed(2)+' g':'Unavailable'],['GPS speed',g?.fix&&g.speed!==null?g.speed.toFixed(1)+' km/h':'No fresh fix'],['Position',g?.fix?`${g.lat.toFixed(6)}, ${g.lon.toFixed(6)}`:'No fresh fix'],['Ice','Not measured']];
 el('historyValues').replaceChildren();for(const [label,value]of values){const box=document.createElement('div');box.textContent=label;const strong=document.createElement('strong');strong.textContent=value;box.append(strong);el('historyValues').append(box);}
 drawHistory(i,g);
}
function drawHistory(index,gps){
 const canvas=el('historyMap'),width=canvas.getBoundingClientRect().width||600,height=240,scale=window.devicePixelRatio||1;canvas.width=width*scale;canvas.height=height*scale;
 const c=canvas.getContext('2d');c.scale(scale,scale);c.fillStyle='#eaf0e3';c.fillRect(0,0,width,height);c.font='12px system-ui';c.fillStyle='#365041';
 const points=history.slice(0,index+1).filter(r=>r.data?.type===2&&r.data.fix).map(r=>r.data);
 if(!points.length){c.fillText('No GPS fix in this part of the recording yet',20,120);return;}
 const first=points[0],cos=Math.cos(first.lat*Math.PI/180),xy=p=>[(p.lon-first.lon)*cos*111320,(p.lat-first.lat)*111320];
 const coords=points.map(xy);let minX=0,maxX=0,minY=0,maxY=0;for(const [x,y]of coords){minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
 const ratio=Math.min((width-60)/Math.max(20,maxX-minX),(height-70)/Math.max(20,maxY-minY));
 const screen=([x,y])=>[width/2+(x-(minX+maxX)/2)*ratio,height/2-(y-(minY+maxY)/2)*ratio];
 c.strokeStyle='#3f765d';c.lineWidth=3;c.beginPath();coords.forEach((p,i)=>{const [x,y]=screen(p);if(i)c.lineTo(x,y);else c.moveTo(x,y);});c.stroke();
 const [x,y]=screen(coords.at(-1));c.fillStyle=gps?.fix?'#254f40':'#899383';c.beginPath();c.arc(x,y,7,0,2*Math.PI);c.fill();
 c.fillStyle='#365041';c.fillText('Saved GPS route · north up · '+(gps?.fix?'position at selected time':'last recorded fix'),14,20);c.fillText(`100 px ≈ ${Math.round(100/ratio)} m`,14,height-12);
}
window.addEventListener('resize',()=>{if(history.length)showFrame();});
el('downloadPart').onclick=()=>{
 if(!selected||!history.length)return;const blob=new Blob([JSON.stringify({sessionId:selected.id,session:selected.data(),note:'Loaded portion only; use Next portion for longer trips.',records:history},null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`RoadMonitor_${selected.id}_${history[0].receivedAtMs}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
buttons();
