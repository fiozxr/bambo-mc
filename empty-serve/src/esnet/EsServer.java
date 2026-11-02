package esnet;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

/**
 * empty-serve milestone 2: server-list ping/pong PLUS the RakNet-style connection
 * handshake a real client performs immediately before it tries to log in.
 *
 *   0x01 ping                       -> 0x1c pong            (milestone 1)
 *   0x05 OPEN_CONNECTION_REQUEST_1  -> 0x06 REPLY_1
 *   0x07 OPEN_CONNECTION_REQUEST_2  -> 0x08 REPLY_2
 *
 * After 0x08 the client sends an ENCRYPTED login (DTLS + AES). This server does not
 * implement that wall, so it detects the attempt and stops with a clear message rather
 * than pretending a session started. Original code, MIT.
 */
public final class EsServer {

    static final byte[] MAGIC = new byte[] {
        0x00, (byte) 0xff, (byte) 0xff, 0x00, (byte) 0xfe, (byte) 0xfe, (byte) 0xfe, (byte) 0xfe,
        (byte) 0xfd, (byte) 0xfd, (byte) 0xfd, (byte) 0xfd, 0x12, 0x34, 0x12, 0x34
    };
    static final byte[] SERVER_ID = new byte[] {0x0e, 0x57, 0x1c, 0x2f, 0x3a, 0x4b, 0x5c, 0x6d};

    static final int ID_PING  = 0x01, ID_PONG = 0x1c;
    static final int ID_OCR1  = 0x05, ID_OCR2 = 0x07;
    static final int ID_OCS1  = 0x06, ID_OCS2 = 0x08;

    static final int PROTOCOL = 2193;          // Bedrock 1.26.50
    static final String VERSION = "1.26.50";
    static final String MOTD = "empty-serve";
    static final String WORLD = "world";

    // One server identity + handshake token (per-session tokens are the correct model; this
    // structural milestone uses one, noted as a simplification toward real-client validation).
    static java.security.KeyPair SERVER_KP;
    static byte[] HANDSHAKE_TOKEN;
    static {
        try {
            SERVER_KP = Crypto.identityKeyPair();
            HANDSHAKE_TOKEN = new byte[16];
            new java.security.SecureRandom().nextBytes(HANDSHAKE_TOKEN);
        } catch (Exception e) { throw new ExceptionInInitializerError(e); }
    }

    /** Build a framed SERVER_TO_CLIENT_HANDSHAKE (inner id 3) carrying a valid ES384 JWT. */
    static byte[] serverToClientHandshake(InetSocketAddress peer) throws Exception {
        String jwt = Handshake.createJwt(SERVER_KP, HANDSHAKE_TOKEN);
        byte[] jwtBytes = jwt.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        java.io.ByteArrayOutputStream inner = new java.io.ByteArrayOutputStream();
        byte[] id = Framing.writeVarInt(3);                    // SERVER_TO_CLIENT_HANDSHAKE
        inner.write(id, 0, id.length);
        byte[] strLen = Framing.writeVarInt(jwtBytes.length);  // Bedrock string length prefix
        inner.write(strLen, 0, strLen.length);
        inner.write(jwtBytes);
        return Framing.encodeFrame(1, new byte[][]{inner.toByteArray()});
    }

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 19134;
        try (DatagramSocket sock = new DatagramSocket(port)) {
            System.out.printf("empty-serve on udp/%d  protocol %d (%s)%n", port, PROTOCOL, VERSION);
            byte[] buf = new byte[2048];
            DatagramPacket req = new DatagramPacket(buf, buf.length);
            while (!sock.isClosed()) {
                sock.receive(req);
                byte[] reply = handle(buf, req.getLength(), (InetSocketAddress) req.getSocketAddress());
                if (reply != null)
                    sock.send(new DatagramPacket(reply, reply.length, req.getSocketAddress()));
                req.setLength(buf.length);
            }
        }
    }

    static byte[] handle(byte[] d, int len, InetSocketAddress peer) {
        if (len < 17) return null;
        byte id = d[0];
        switch (id) {
            case ID_PING: return pong(d, len);
            case ID_OCR1: return reply1();
            case ID_OCR2: return reply2(d, peer);
            case (byte) 0xfe: case (byte) 0xad: {
                Framing.Frame f = Framing.decodeFrame(java.util.Arrays.copyOf(d, len));
                if (f == null || f.packets().length == 0) return null;
                int innerId = f.packets()[0][0] & 0xff;
                if (innerId == 1) { // LOGIN
                    System.out.println("  -> " + peer + " sent LOGIN; replying SERVER_TO_CLIENT_HANDSHAKE");
                    try {
                        return serverToClientHandshake(peer);
                    } catch (Exception e) {
                        System.out.println("  handshake build failed: " + e);
                        return null;
                    }
                }
                System.out.println("  [!] " + peer + " sent framed inner id 0x"
                        + Integer.toHexString(innerId) + " beyond LOGIN. Session NOT started.");
                return null;
            }
            default: return null;
        }
    }

    static byte[] pong(byte[] d, int len) {
        for (int i = 0; i < 16; i++) if (d[1 + i] != MAGIC[i]) return null;
        ByteBuffer b = ByteBuffer.allocate(2048).order(ByteOrder.LITTLE_ENDIAN);
        b.put((byte) ID_PONG); b.put(MAGIC);
        long ts = ByteBuffer.wrap(d, 17, 8).order(ByteOrder.LITTLE_ENDIAN).getLong();
        b.putLong(ts); b.put(new byte[8]);
        putStr(b, new String(MAGIC, StandardCharsets.ISO_8859_1));
        putStr(b, "MCPE"); putStr(b, VERSION);
        b.putInt(PROTOCOL); putStr(b, VERSION);
        putStr(b, MOTD);
        b.putLong(0); b.putLong(20); putStr(b, "esnet"); putStr(b, WORLD);
        b.putLong(0); b.putLong(0);
        return trim(b);
    }

    static byte[] reply1() {
        ByteBuffer b = ByteBuffer.allocate(64).order(ByteOrder.LITTLE_ENDIAN);
        b.put((byte) ID_OCS1); b.put(MAGIC); b.put(SERVER_ID);
        b.put((byte) 0);           // security mode: 0 = no server-side encryption offer
        b.putShort((short) 1400);  // MTU
        return trim(b);
    }

    static byte[] reply2(byte[] d, InetSocketAddress peer) {
        ByteBuffer b = ByteBuffer.allocate(64).order(ByteOrder.LITTLE_ENDIAN);
        b.put((byte) ID_OCS2); b.put(MAGIC); b.put(SERVER_ID);
        byte[] ip = peer.getAddress().getAddress();  // 4 bytes for IPv4
        if (ip.length != 4) ip = new byte[]{127, 0, 0, 1};
        b.put(ip);
        b.putShort((short) (peer.getPort() & 0xffff));
        b.put((byte) 0);           // security mode echoed
        return trim(b);
    }

    static void putStr(ByteBuffer b, String s) {
        byte[] r = s.getBytes(StandardCharsets.UTF_8);
        b.putLong(r.length); b.put(r);
    }
    static byte[] trim(ByteBuffer b) { byte[] o = new byte[b.position()]; b.flip(); b.get(o); return o; }
}
