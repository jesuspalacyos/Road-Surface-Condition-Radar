import struct
import numpy as np
MAGIC = bytes.fromhex('0201040306050807')

class Decoder:
    def __init__(self, bins):
        self.buf = bytearray()
        self.bins = bins
        self.bad = 0

    def feed(self, data):
        self.buf.extend(data)
        out = []
        while True:
            i = self.buf.find(MAGIC)
            if i < 0:
                self.buf[:] = self.buf[-7:]
                break
            if i:
                del self.buf[:i]
            if len(self.buf) < 40:
                break
            version, size, platform, frame, cycles, objects, count, sub = struct.unpack_from('<8I', self.buf, 8)
            if size < 40 or size > 1048576 or count > 64:
                del self.buf[0]
                self.bad += 1
                continue
            if len(self.buf) < size:
                # Resynchronize if a corrupt length masks a subsequent complete packet.
                j = self.buf.find(MAGIC, 8)
                if j >= 0 and len(self.buf) >= j+40:
                    next_size = struct.unpack_from('<I', self.buf, j+12)[0]
                    if 40 <= next_size <= len(self.buf)-j:
                        del self.buf[:j]
                        self.bad += 1
                        continue
                break
            packet = bytes(self.buf[:size])
            del self.buf[:size]
            pos, profile, valid = 40, None, True
            for _ in range(count):
                if pos+8 > size:
                    valid = False
                    break
                typ, length = struct.unpack_from('<II', packet, pos)
                pos += 8
                # SDK 3.x OOB length excludes the 8-byte TLV header.
                if pos+length > size:
                    valid = False
                    break
                if typ == 2:
                    if length != self.bins*2:
                        valid = False
                        break
                    profile = np.frombuffer(packet, dtype='<u2', count=self.bins, offset=pos).astype(float)
                pos += length
            if valid and profile is not None and sub == 0:
                out.append((frame, profile))
            elif not valid:
                self.bad += 1
        return out

