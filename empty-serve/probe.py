import socket, struct, time, sys
MAGIC = bytes([0,0xff,0xff,0,0xfe,0xfe,0xfe,0xfe,0xfd,0xfd,0xfd,0xfd,0x12,0x34,0x12,0x34])
def s(x): b=x if isinstance(x,(bytes,bytearray)) else x.encode(); return struct.pack('<Q',len(b))+b
def rd(b,i): n=struct.unpack_from('<Q',b,i)[0]; return b[i+8:i+8+n].decode('utf8','replace'), i+8+n
port=int(sys.argv[1]) if len(sys.argv)>1 else 19133
ping=b'\x01'+MAGIC+struct.pack('<Q',int(time.time()*1000))+b'\x00'*8+s(MAGIC)+struct.pack('<Q',2193)+s('1.26.50')+s('esnet-probe')+struct.pack('<QQ',19133,19132)
u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); u.settimeout(3); u.sendto(ping,('127.0.0.1',port))
d,_=u.recvfrom(4096)
ok=True
def chk(c,l):
    global ok
    print(('  PASS ' if c else '  FAIL ')+l); ok=ok and c
chk(d[0]==0x1c, f"packet id is pong 0x1c (got 0x{d[0]:02x})")
chk(d[1:17]==MAGIC, "reply echoes the 16-byte offline magic")
i=17+8+8
magic2,i=rd(d,i); chk(magic2==MAGIC.decode('iso-8859-1'), "magic2 string decodes")
ed,i=rd(d,i);   chk(ed=='MCPE', f"edition == 'MCPE' (got '{ed}')")
v1,i=rd(d,i);   chk(v1=='1.26.50', f"version1 == 1.26.50 (got '{v1}')")
proto=struct.unpack_from('<i',d,i)[0]; i+=4; chk(proto==2193, f"protocol == 2193 (got {proto})")
v2,i=rd(d,i);   motd,i=rd(d,i)
on=struct.unpack_from('<q',d,i)[0]; mx=struct.unpack_from('<q',d,i+8)[0]
chk(motd=='empty-serve', f"MOTD == 'empty-serve' (got '{motd}')")
chk(on==0 and mx==20, f"player counts 0/20 (got {on}/{mx})")
print("RESULT:", "STRUCTURALLY VALID" if ok else "MALFORMED")
sys.exit(0 if ok else 1)
