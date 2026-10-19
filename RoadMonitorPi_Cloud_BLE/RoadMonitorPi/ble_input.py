"""ESP32 framed notifications: uint16 LE sequence, uint8 index, uint8 total, <=16 payload bytes."""
import asyncio, json, time
SERVICE='6e400001-b5a3-f393-e0a9-e50e24dcca9e'
CHARACTERISTIC='6e400003-b5a3-f393-e0a9-e50e24dcca9e'
class Assembler:
    def __init__(self): self.seq=None;self.parts=[];self.total=0;self.started=0
    def feed(self,data):
        if not 5<=len(data)<=20:return None
        seq=int.from_bytes(data[:2],'little');index,total=data[2:4]
        if not 1<=total<=64 or index>=total:return None
        if index==0:
            self.seq=seq;self.parts=[];self.total=total;self.started=time.monotonic()
        if seq!=self.seq or total!=self.total or index!=len(self.parts) or time.monotonic()-self.started>1:
            self.seq=None;self.parts=[];return None
        self.parts.append(bytes(data[4:]))
        if len(self.parts)==total:
            raw=b''.join(self.parts);self.seq=None;self.parts=[]
            return json.loads(raw)
        return None

async def run(m,address,lock):
    from bleak import BleakClient, BleakScanner
    while True:
        try:
            if address=='auto':
                device=await BleakScanner.find_device_by_filter(lambda d,a:a.local_name=='RoadMonitor-S3' and SERVICE in a.service_uuids,timeout=15)
            else: device=await BleakScanner.find_device_by_address(address,timeout=15)
            if device is None:raise RuntimeError('ESP32 not found; check BLE firmware, power, and Pi Bluetooth.')
            assembler=Assembler()
            def receive(_,data):
                try:
                    packet=assembler.feed(data)
                    if packet is not None:
                        with lock:
                            m.raw=json.dumps(packet)
                            if not m.ingest(packet):raise ValueError('Invalid sensor packet')
                            m.errors.pop('ble',None)
                except (ValueError,TypeError,UnicodeError) as exc:
                    with lock:m.errors['ble']=str(exc)
            async with BleakClient(device) as client:
                await client.start_notify(CHARACTERISTIC,receive)
                with lock:m.errors.pop('ble',None)
                while client.is_connected:await asyncio.sleep(.5)
            raise RuntimeError('ESP32 disconnected; reconnecting')
        except Exception as exc:
            with lock:m.errors['ble']=str(exc)
            await asyncio.sleep(2)

def ble_loop(m,address,lock):
    try:asyncio.run(run(m,address,lock))
    except Exception as exc:
        with lock:m.errors['ble']=str(exc)
