"""TI xWR68xx mmWave SDK 3.x out-of-box UART only; not tracking/compressed TLVs."""
import struct, math
MAGIC=b'\x02\x01\x04\x03\x06\x05\x08\x07'
class Parser:
    def __init__(self): self.buffer=bytearray(); self.rejected=0
    def feed(self,data):
        self.buffer.extend(data); frames=[]
        while True:
            i=self.buffer.find(MAGIC)
            if i<0:
                self.buffer=self.buffer[-7:]; break
            if i: del self.buffer[:i]
            if len(self.buffer)<40: break
            version,total,platform,frame,ticks,objects,ntlv,sub=struct.unpack_from('<8I',self.buffer,8)
            if total<40 or total>1048576 or ntlv>128 or objects>65536:
                del self.buffer[:8]; self.rejected+=1; continue
            if len(self.buffer)<total: break
            packet=bytes(self.buffer[:total]); del self.buffer[:total]
            try:
                pts=[]; power=None; off=40; seen=False
                for _ in range(ntlv):
                    if off+8>total: raise ValueError('short TLV header')
                    typ,n=struct.unpack_from('<II',packet,off); off+=8
                    # SDK 3 OOB TLV length excludes its 8-byte header.
                    if off+n>total: raise ValueError('short TLV body')
                    body=packet[off:off+n]; off+=n
                    if typ==1:
                        if n!=objects*16: raise ValueError('not SDK3 float Cartesian points')
                        pts=list(struct.iter_unpack('<ffff',body)); seen=True
                        if not all(all(math.isfinite(v) for v in p) for p in pts): raise ValueError('nonfinite point')
                    if typ==2 and n and n%2==0:
                        vals=struct.unpack('<'+'H'*(n//2),body); power=sum(vals)/len(vals)
                if objects and not seen: raise ValueError('point TLV missing; verify guiMonitor / firmware')
                frames.append({'frame':frame,'points':pts,'range_power_mean':power})
            except (ValueError,struct.error): self.rejected+=1
        return frames

def configure(port,path):
    import serial, time
    with serial.Serial(port,115200,timeout=.2) as cli:
        time.sleep(.3); cli.reset_input_buffer()
        for line in open(path):
            line=line.strip()
            if not line or line.startswith(('%','#')): continue
            cli.write((line+'\n').encode()); answer=b''; end=time.monotonic()+4
            while time.monotonic()<end:
                answer+=cli.read(4096)
                if b'Done' in answer or b'Error' in answer or b'not recognized' in answer: break
            if b'Done' not in answer or b'Error' in answer:
                raise RuntimeError('Radar rejected/timed out: '+line+' | '+answer.decode(errors='replace')[-200:])
