import socket, struct, time, sys
MAGIC = bytes([0,0xff,0xff,0,0xfe,0xfe,0xfe,0xfe,0xfd,0xfd,0xfd,0xfd,0x12,0x34,0x12,0x34])
port=int(sys.argv[1]) if len(sys.argv)>1 else 19135
u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); u.settimeout(3)
def txrx(p,label):
    u.sendto(p,('127.0.0.1',port)); d,_=u.recvfrom(4096); print(f"  {label}: reply id=0x{d[0]:02x} ({len(d)}B)"); return d
d=txrx(b'\x01'+MAGIC+struct.pack('<Q',int(time.time()*1000))+b'\x00'*28,'ping'); assert d[0]==0x1c
d=txrx(b'\x05'+MAGIC+b'\x00'*20,'OCR1'); assert d[0]==0x06
sec=d[25]; mtu=struct.unpack_from('<H',d,26)[0]
print(f"    REPLY_1 serverId={d[17:25].hex()} security={sec} MTU={mtu}"); assert sec==0 and mtu>0
d=txrx(b'\x07'+MAGIC+bytes([127,0,0,1])+struct.pack('<H',12345)+struct.pack('<H',1400)+b'\x00'*9,'OCR2'); assert d[0]==0x08
ip='.'.join(str(x) for x in d[25:29]); prt=struct.unpack_from('<H',d,29)[0]; sec=d[31]
print(f"    REPLY_2 clientaddr={ip}:{prt} security={sec}"); assert sec==0
print("RESULT: HANDSHAKE OK (ping -> REPLY_1 -> REPLY_2)")
