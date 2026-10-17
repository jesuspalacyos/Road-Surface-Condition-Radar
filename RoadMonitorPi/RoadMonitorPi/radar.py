"""TI mmWave SDK 3.x out-of-box: 40-byte header, TLV 1 float XY Z velocity.
Not compatible with compressed point clouds / people-tracking firmware.
"""
import struct, math
MAGIC = bytes.fromhex('0201040306050807')
class RadarParser:
    def __init__(self): self.buf = bytearray()
    def feed(self, data):
        self.buf.extend(data); frames=[]
        while True:
            i=self.buf.find(MAGIC)
            if i<0:
                self.buf=self.buf[-7:]; break
            if i: del self.buf[:i]
            if len(self.buf)<40: break
            version,total,platform,frame,cycles,n,ntlv,sub=struct.unpack_from('<8I',self.buf,8)
            if not 40<=total<=1048576 or ntlv>128 or n>65536:
                del self.buf[0]; continue
            if len(self.buf)<total: break
            pkt=bytes(self.buf[:total]); del self.buf[:total]
            pos=40; points=[]; types=[]; valid=True; found=False; snr=None
            for _ in range(ntlv):
                if pos+8>total: valid=False; break
                typ,size=struct.unpack_from('<II',pkt,pos); pos+=8; types.append(typ)
                if pos+size>total: valid=False; break
                if typ==1:
                    found=True
                    if size!=16*n: valid=False; break
                    for p in struct.iter_unpack('<4f',pkt[pos:pos+size]):
                        if not all(math.isfinite(v) for v in p): valid=False; break
                        points.append(dict(zip(('x','y','z','v'),p)))
                elif typ==7 and size==4*n:
                    # Side info: int16 SNR and noise per point, units of 0.1 dB.
                    snr=[a/10.0 for a,_ in struct.iter_unpack('<hh',pkt[pos:pos+size])]
                pos+=size
            if valid:
                for i,pt in enumerate(points):
                    pt['snr']=snr[i] if snr is not None and i<len(snr) else None
                frames.append({'frame':frame,'points':points,'types':types,
                               'supported':found or n==0})
        return frames
