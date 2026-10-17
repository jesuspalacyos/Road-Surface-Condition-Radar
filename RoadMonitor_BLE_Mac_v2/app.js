'use strict';
const SERVICE='8e2a0001-7c43-4f58-90f0-7a5e90401a01';
const DATA='8e2a0002-7c43-4f58-90f0-7a5e90401a01';
const COMMAND='8e2a0003-7c43-4f58-90f0-7a5e90401a01';
const $=id=>document.getElementById(id);
const set=(id,value)=>{$(id).textContent=value;};
let device=null, characteristic=null, command=null, busy=false, live=false, demoTimer=null;
let sensor=null, gps=null, sensorAt=0, gpsAt=0, events=[], route=[], lastEventAt=0;
let candidate='', consecutive=0, zoom=18, center=null, tileErrors=false, tileGeneration=0;
const tiles=new Map();
const isDemo=()=>demoTimer!==null;
const usableGPS=()=>gps && gps.fix && Date.now()-gpsAt<3000;
function clearSession(){sensor=gps=null;sensorAt=gpsAt=0;candidate='';consecutive=0;route=[];center=null;events=[];lastEventAt=0;renderEvents();drawMap();}
function message(s){set('message',s);}
function decode(view){
  if(view.byteLength!==20 || view.getUint8(1)!==1) throw Error('Unexpected packet. Upload the matching v2 firmware.');
  const type=view.getUint8(0), f=view.getUint8(2), u16=n=>view.getUint16(n,true);
  const base={deviceUptimeMs:view.getUint32(4,true),rawPacket:Array.from(new Uint8Array(view.buffer,view.byteOffset,view.byteLength))};
  if(type===1) return {...base,xG:view.getInt16(14,true)/1000,yG:view.getInt16(16,true)/1000,zG:view.getInt16(18,true)/1000,type,accelCal:!!(f&1),tofReady:!!(f&2),rangeValid:!!(f&4),accelValid:!!(f&8),tofCal:!!(f&16),calibrating:!!(f&32),vibration:u16(8)===65535?null:u16(8)/1000,distance:u16(10)===65535?null:u16(10),baseline:u16(12)===65535?null:u16(12)};
  if(type===2){
    const lat=view.getInt32(8,true)/1e7,lon=view.getInt32(12,true)/1e7;
    return {...base,type,fix:!!(f&1)&&Math.abs(lat)<=90&&Math.abs(lon)<=180,serial:!!(f&4),lat,lon,speed:(f&2)&&u16(16)!==65535?u16(16)/100:null,satellites:view.getUint8(3)===255?null:view.getUint8(3),hdop:u16(18)===65535?null:u16(18)/100};
  }
  throw Error('Unknown packet type.');
}
function accept(data){
  const now=Date.now();
  if(data.type===1){sensor=data;sensorAt=now;observe();}
  else {gps=data;gpsAt=now;if(data.fix){center=[data.lat,data.lon];const prev=route[route.length-1];if(!prev || Math.abs(prev[0]-data.lat)+Math.abs(prev[1]-data.lon)>0.000005){route.push(center);if(route.length>5000)route.shift();}drawMap();}}
  render();
  window.dispatchEvent(new CustomEvent('roadmonitor:reading',{detail:{receivedAtMs:now,simulated:isDemo(),data,assessment:data.type===1?assessment():null,thresholds:{rangeMM:threshold('rangeThreshold',40,10,300),vibrationG:threshold('vibrationThreshold',.35,.1,3)}}}));
}
function notification(e){try{accept(decode(e.target.value));}catch(err){message(err.message);}}
function disconnectState(){
  window.dispatchEvent(new CustomEvent('roadmonitor:ended',{detail:'disconnected'}));
  live=false;command=null;sensor=gps=null;sensorAt=gpsAt=0;candidate='';consecutive=0;
  $('calibrate').disabled=true;$('disconnect').disabled=true;$('connect').disabled=false;$('scanAll').disabled=false;
  render();drawMap();
}
async function connect(all=false){
  if(busy)return;
  if(!window.isSecureContext){message('Open http://localhost:8000/dashboard.html in Chrome. Bluetooth requires localhost or HTTPS.');return;}
  if(!navigator.bluetooth){message('Web Bluetooth is unavailable here. Open this page in Google Chrome on your Mac, not Safari or Firefox.');return;}
  if(isDemo()) stopDemo();
  busy=true;$('connect').disabled=true;$('scanAll').disabled=true;$('demo').disabled=true;
  try{
    message('Select RoadMonitor-S3 in the Bluetooth chooser.');
    device=await navigator.bluetooth.requestDevice(all?{acceptAllDevices:true,optionalServices:[SERVICE]}:{filters:[{namePrefix:'RoadMonitor'}],optionalServices:[SERVICE]});
    device.addEventListener('gattserverdisconnected',onDisconnect);
    message('Connecting and subscribing to readings…');
    const server=await device.gatt.connect();
    const service=await server.getPrimaryService(SERVICE);
    characteristic=await service.getCharacteristic(DATA);
    command=await service.getCharacteristic(COMMAND);
    clearSession();
    characteristic.addEventListener('characteristicvaluechanged',notification);
    await characteristic.startNotifications();
    live=true;$('disconnect').disabled=false;$('calibrate').disabled=false;
    message('Connected. Place the mounted sensors over flat ground and keep still, then click Calibrate.');
  }catch(err){
    if(characteristic)characteristic.removeEventListener('characteristicvaluechanged',notification);
    if(device){device.removeEventListener('gattserverdisconnected',onDisconnect);if(device.gatt.connected)device.gatt.disconnect();}
    disconnectState();
    message(err.name==='NotFoundError'?'No device selected. If the list was empty, reset the board, check its antenna and Chrome Bluetooth permission, then use “Find device without name filter”.':`Connection failed: ${err.message}. Close other BLE apps and make sure the matching firmware is uploaded.`);
  }finally{busy=false;$('demo').disabled=false;$('connect').disabled=live;$('scanAll').disabled=live;render();}
}
function onDisconnect(){if(characteristic)characteristic.removeEventListener('characteristicvaluechanged',notification);disconnectState();message('Bluetooth disconnected. Previous route and observations are retained; readings are no longer live. Click Connect to start a new session.');}
$('connect').onclick=()=>connect();$('scanAll').onclick=()=>connect(true);
$('disconnect').onclick=()=>{if(device?.gatt.connected)device.gatt.disconnect();};
$('calibrate').onclick=async()=>{
  if(!command)return;
  $('calibrate').disabled=true;
  try{await command.writeValueWithResponse(new Uint8Array([67]));message('Calibration requested. Keep completely still over flat ground for 3 seconds.');}
  catch(err){message(`Calibration failed: ${err.message}`);}
  finally{setTimeout(()=>{$('calibrate').disabled=!live;},3500);}
};
function threshold(id,fallback,min,max){const n=Number($(id).value);return Number.isFinite(n)?Math.min(max,Math.max(min,n)):fallback;}
function assessment(){
  if(!sensor || Date.now()-sensorAt>2000)return {key:'unknown',title:live?'Waiting for fresh readings':'Ready when you are.',detail:live?'No recent sensor data. Check the board power and BLE connection.':'Connect your board or try the clearly labeled simulation.'};
  if(sensor.calibrating)return {key:'cal',title:'Learning your flat surface…',detail:'Keep the sensors still until calibration is complete.'};
  const rangeOK=sensor.tofCal&&sensor.rangeValid&&sensor.distance!==null&&sensor.baseline!==null;
  const accelOK=sensor.accelCal&&sensor.accelValid&&sensor.vibration!==null;
  if(!rangeOK && !accelOK)return {key:'unknown',title:'Setup needs attention',detail:'Calibrate first. Check wiring and sensor range if readings remain unavailable.'};
  const delta=rangeOK?sensor.distance-sensor.baseline:null;
  const limit=threshold('rangeThreshold',40,10,300);
  if(delta!==null&&delta>limit)return {key:'dip',title:'Possible dip beneath the sensor',detail:'Ground appears farther away. This may be a pothole, or a change in vehicle height or tilt.',delta};
  if(delta!==null&&delta< -limit)return {key:'raised',title:'Possible raised surface',detail:'Ground appears closer. This may be debris, a bump, or vehicle movement.',delta};
  if(accelOK&&sensor.vibration>threshold('vibrationThreshold',.35,.1,3))return {key:'vibration',title:'Strong movement measured',detail:'The accelerometer recorded a jolt or tilt. It does not identify the cause.',delta};
  return {key:'quiet',title:'No large change in available readings',detail:rangeOK&&accelOK?'Readings are below your thresholds. This does not establish that the road is safe.':'Some readings are unavailable. Check calibration, wiring and distance range.',delta};
}
function observe(){
  const a=assessment();
  if(a.key===candidate)consecutive++;else{candidate=a.key;consecutive=1;}
  if(!['dip','raised','vibration'].includes(a.key)||consecutive<(a.key==='vibration'?1:2)||Date.now()-lastEventAt<2000)return;
  lastEventAt=Date.now();
  events.unshift({time:new Date().toISOString(),kind:a.key==='dip'?'Possible dip':a.key==='raised'?'Possible raised surface':'Strong movement',delta:a.delta??null,lat:usableGPS()?gps.lat:null,lon:usableGPS()?gps.lon:null,simulated:isDemo()});
  if(events.length>1000)events.pop();renderEvents();
}
function render(){
  const fresh=sensor&&Date.now()-sensorAt<=2000,a=assessment();
  set('connection',isDemo()?'SIMULATED':live?'BLE connected':'Disconnected');
  set('mode',isDemo()?'SIMULATION · NO REAL SENSOR DATA':fresh?'LIVE SENSOR READINGS':'WAITING FOR SENSOR');
  set('summary',a.title);set('summaryDetail',a.detail);
  const rangeOK=fresh&&sensor.tofCal&&sensor.rangeValid&&!sensor.calibrating;
  set('pothole',!rangeOK?'Not assessed':a.key==='dip'?(consecutive>=2?'Possible dip':'Checking change…'):'No dip flag');
  set('debris',!rangeOK?'Not assessed':a.key==='raised'?(consecutive>=2?'Possible raised surface':'Checking change…'):'No raised-surface flag');
  $('pothole').className=a.key==='dip'?'warn':'';$('debris').className=a.key==='raised'?'warn':'';
  set('distance',fresh&&sensor.rangeValid&&sensor.distance!==null?`${(sensor.distance/10).toFixed(1)} cm`:'Unavailable');
  set('change',rangeOK?`${sensor.distance-sensor.baseline>0?'+':''}${sensor.distance-sensor.baseline} mm`:'—');
  set('vibration',fresh&&sensor.accelCal&&sensor.accelValid&&sensor.vibration!==null?`${sensor.vibration.toFixed(2)} g`:'Unavailable');
  set('calStatus',!fresh?'Needed':sensor.calibrating?'Keep still…':sensor.accelCal&&sensor.tofCal?'Complete':sensor.accelCal||sensor.tofCal?'Partial · retry':'Needed');
  set('age',sensorAt?`${((Date.now()-sensorAt)/1000).toFixed(1)} s ago`:'—');
  set('speed',usableGPS()&&gps.speed!==null?gps.speed.toFixed(1):'—');
  set('satellites',gps&&Date.now()-gpsAt<3000?gps.satellites??'—':'—');
  set('gpsStatus',usableGPS()?(isDemo()?'Simulated route':`GPS fix · ${gps.hdop!==null?'HDOP '+gps.hdop.toFixed(1):'accuracy unknown'}`):gps&&Date.now()-gpsAt<3000?(gps.serial?'GPS data received · waiting for outdoor fix':'No GPS serial data · check TX → D7'):'Waiting for fresh GPS data');
  set('coordinates',usableGPS()?`${gps.lat.toFixed(6)}, ${gps.lon.toFixed(6)}`:center?'Last known location · not live':'No location yet');
}
function renderEvents(){
  const body=$('events');body.replaceChildren();
  if(!events.length){const tr=body.insertRow(),td=tr.insertCell();td.colSpan=4;td.textContent='No observations yet.';}
  for(const e of events.slice(0,12)){
    const tr=body.insertRow();
    [new Date(e.time).toLocaleTimeString(),(e.simulated?'[SIM] ':'')+e.kind,e.delta===null?'—':`${e.delta} mm`,e.lat===null?'No GPS fix':`${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}`].forEach(v=>tr.insertCell().textContent=v);
  }
  $('export').disabled=events.length===0;
}
$('export').onclick=()=>{
  const rows=[['time_utc','observation','distance_change_mm','latitude','longitude','simulated'],...events.map(e=>[e.time,e.kind,e.delta??'',e.lat??'',e.lon??'',e.simulated])];
  const csv=rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'})),a=document.createElement('a');a.href=url;a.download=`RoadMonitor_${isDemo()?'SIMULATED_':''}${Date.now()}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
// Map uses a self-contained route canvas. OSM tiles are requested only after opt-in.
function project(lat,lon){const scale=256*2**zoom,s=Math.sin(Math.max(-85.0511,Math.min(85.0511,lat))*Math.PI/180);return [(lon+180)/360*scale,(.5-Math.log((1+s)/(1-s))/(4*Math.PI))*scale];}
function drawMap(){
  const canvas=$('map'),rect=canvas.getBoundingClientRect(),w=rect.width||600,h=280,dpr=window.devicePixelRatio||1;
  canvas.width=Math.round(w*dpr);canvas.height=h*dpr;const c=canvas.getContext('2d');c.scale(dpr,dpr);c.fillStyle='#eaf0e3';c.fillRect(0,0,w,h);
  c.strokeStyle='#d6dfd0';c.lineWidth=1;for(let x=0;x<w;x+=40){c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.stroke();}for(let y=0;y<h;y+=40){c.beginPath();c.moveTo(0,y);c.lineTo(w,y);c.stroke();}
  if(!center){c.fillStyle='#65745e';c.font='14px system-ui';c.textAlign='center';c.fillText('Your route appears after a GPS fix',w/2,h/2);return;}
  const p=project(...center),left=p[0]-w/2,top=p[1]-h/2;
  if($('streets').checked){
    for(let x=Math.floor(left/256);x<=Math.floor((left+w)/256);x++)for(let y=Math.floor(top/256);y<=Math.floor((top+h)/256);y++){
      const n=2**zoom;if(y<0||y>=n)continue;const wrapped=((x%n)+n)%n,key=`${zoom}/${wrapped}/${y}`;
      let tile=tiles.get(key);if(!tile){tile=new Image();tiles.set(key,tile);const generation=tileGeneration;tile.onload=()=>{if(generation===tileGeneration)drawMap();};tile.onerror=()=>{if(generation===tileGeneration){tileErrors=true;set('attribution','Street tiles unavailable · offline route shown');}};tile.src=`https://tile.openstreetmap.org/${key}.png`;}
      if(tile.complete&&tile.naturalWidth)c.drawImage(tile,x*256-left,y*256-top,256,256);
    }
    if(tiles.size>160){for(const [key,tile]of tiles){tile.onload=tile.onerror=null;tiles.delete(key);if(tiles.size<=100)break;}}
  }
  c.strokeStyle='#3f765d';c.lineWidth=3;c.lineJoin='round';c.beginPath();route.forEach((v,i)=>{const q=project(...v);if(i)c.lineTo(q[0]-left,q[1]-top);else c.moveTo(q[0]-left,q[1]-top);});c.stroke();
  c.fillStyle=usableGPS()?'#244f40':'#869380';c.beginPath();c.arc(w/2,h/2,8,0,Math.PI*2);c.fill();c.strokeStyle='white';c.lineWidth=3;c.stroke();
  const metersPerPixel=156543.03392*Math.cos(center[0]*Math.PI/180)/2**zoom;
  c.fillStyle='#fff';c.fillRect(10,h-30,125,22);c.fillStyle='#365041';c.font='11px system-ui';c.fillText(`100 px ≈ ${Math.round(metersPerPixel*100)} m`,16,h-15);
}
$('streets').onchange=()=>{tileErrors=false;tileGeneration++;for(const tile of tiles.values())tile.onload=tile.onerror=null;tiles.clear();if($('streets').checked){$('attribution').innerHTML='© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>';}else set('attribution','Offline route · north up');drawMap();};
$('zoomIn').onclick=()=>{zoom=Math.min(19,zoom+1);drawMap();};$('zoomOut').onclick=()=>{zoom=Math.max(3,zoom-1);drawMap();};
window.addEventListener('resize',drawMap);
function stopDemo(){window.dispatchEvent(new CustomEvent('roadmonitor:ended',{detail:'simulation-ended'}));clearInterval(demoTimer);demoTimer=null;sensor=gps=null;sensorAt=gpsAt=0;set('demo','Try simulated data');render();drawMap();}
$('demo').onclick=()=>{
  if(live){message('Disconnect the real sensor before starting the simulation.');return;}
  if(isDemo()){stopDemo();message('Simulation stopped. Connect your board for real readings.');return;}
  clearSession();let tick=0;
  demoTimer=setInterval(()=>{
    tick++;const phase=tick%120,delta=phase>=30&&phase<38?85:phase>=70&&phase<78?-65:Math.round(3*Math.sin(tick));
    accept({type:1,accelCal:true,tofReady:true,rangeValid:true,accelValid:true,tofCal:true,calibrating:false,vibration:Math.abs(delta)>20?.52:.04,distance:300+delta,baseline:300});
    if(tick%5===0)accept({type:2,fix:true,serial:true,lat:32.985+tick*.0000008,lon:-96.750+Math.sin(tick/45)*.00015,speed:4.2,satellites:9,hdop:1.1});
  },100);
  set('demo','Stop simulation');message('SIMULATED DATA ONLY. The route and observations below are examples, not measurements. Starting a new connection clears this session; export first if needed.');render();
};
setInterval(()=>{render();drawMap();},1000);
render();drawMap();

window.roadMonitor = {
  status:()=>({live,simulated:isDemo(),fresh:!!sensor&&Date.now()-sensorAt<2000}),
  settings:()=>({rangeMM:threshold('rangeThreshold',40,10,300),vibrationG:threshold('vibrationThreshold',.35,.1,3)})
};
