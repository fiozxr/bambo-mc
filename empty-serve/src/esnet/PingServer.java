package esnet;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

/**
 * empty-serve milestone 1: a Bedrock server-list ping/pong responder.
 *
 * Original code, MIT. No PowerNukkitX / Nukkit lineage. Implements only the
 * "unconnected ping" (0x01) -> "pong" (0x1c) exchange, which is the part that
 * makes a server advertise itself. It does NOT yet accept a game connection.
 *
 * Bedrock strings are a 64-bit little-endian length prefix followed by UTF-8 bytes.
 */
public final class PingServer {

    // The constant 16-byte "offline message" magic that prefixes every unconnected packet.
    static final byte[] MAGIC = new byte[] {
        0x00, (byte) 0xff, (byte) 0xff, 0x00, (byte) 0xfe, (byte) 0xfe, (byte) 0xfe, (byte) 0xfe,
        (byte) 0xfd, (byte) 0xfd, (byte) 0xfd, (byte) 0xfd, 0x12, 0x34, 0x12, 0x34
    };

    // Protocol numbers are tied to a specific client release. These mirror the version
    // the family's phones were on when PNX 3.0.5 worked; adjust when clients move.
    static final int    PROTOCOL   = 2193;         // Bedrock 1.26.50
    static final String VERSION    = "1.26.50";
    static final String MOTD       = "empty-serve";
    static final String WORLD_NAME = "world";

    static final int PACKET_ID  = 0x01; // client's unconnected ping
    static final int PONG_ID    = 0x1c; // our reply
    static final int HEADER_LEN = 16;   // size of the magic block

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 19133;
        try (DatagramSocket sock = new DatagramSocket(port)) {
            System.out.printf("empty-serve ping responder on udp/%d  (protocol %d, %s)%n",
                    port, PROTOCOL, VERSION);
            byte[] buf = new byte[2048];
            DatagramPacket req = new DatagramPacket(buf, buf.length);
            while (!sock.isClosed()) {
                sock.receive(req);
                byte[] reply = handlePing(buf, req.getLength(), (InetSocketAddress) req.getSocketAddress());
                if (reply != null) {
                    sock.send(new DatagramPacket(reply, reply.length,
                            new InetSocketAddress(req.getAddress(), req.getPort())));
                }
                req.setLength(buf.length);
            }
        }
    }

    /** Parse a Bedrock unconnected ping and build the pong, or null if not a ping. */
    static byte[] handlePing(byte[] data, int len, InetSocketAddress peer) {
        if (len < HEADER_LEN + 1 || data[0] != PACKET_ID) return null;
        // Must carry the offline magic at the front to be a real Bedrock ping.
        for (int i = 0; i < HEADER_LEN; i++) if (data[1 + i] != MAGIC[i]) return null;

        ByteBuffer in = ByteBuffer.wrap(data, HEADER_LEN + 1, len - HEADER_LEN - 1)
                .order(ByteOrder.LITTLE_ENDIAN);
        long clientTime = in.getLong();     // sender timestamp (8)
        in.position(in.position() + 8);     // unused zeros (8)
        readString(in);                     // magic2 (the magic again, string-encoded)
        int theirProto = (int) in.getLong();// protocol version
        String theirVer  = readString(in);  // "1.26.50"
        System.out.printf("  ping from %s  proto=%d ver=%s%n", peer.getAddress().getHostAddress(), theirProto, theirVer);

        ByteBuffer out = ByteBuffer.allocate(2048).order(ByteOrder.LITTLE_ENDIAN);
        out.put((byte) PONG_ID);
        out.put(MAGIC);
        out.putLong(clientTime);            // echo timestamp
        out.put(new byte[8]);               // unused
        putString(out, new String(MAGIC, StandardCharsets.ISO_8859_1)); // magic2
        putString(out, "MCPE");             // edition marker clients expect
        putString(out, VERSION);            // version 1
        out.putInt(PROTOCOL);               // protocol number (pong uses a 32-bit int here)
        putString(out, VERSION);            // version 2
        putString(out, MOTD);
        out.putLong(0);                     // online players
        out.putLong(20);                    // max players
        putString(out, "esnet");            // server id (authoritative field name varies)
        putString(out, WORLD_NAME);
        out.putLong(0);                     // default port (unused here)
        out.putLong(0);
        byte[] full = new byte[out.position()];
        out.flip(); out.get(full);
        return full;
    }

    static String readString(ByteBuffer b) {
        int n = (int) b.getLong();
        byte[] s = new byte[n];
        b.get(s);
        return new String(s, StandardCharsets.UTF_8);
    }

    static void putString(ByteBuffer b, String s) {
        byte[] raw = s.getBytes(StandardCharsets.UTF_8);
        b.putLong(raw.length);
        b.put(raw);
    }
}
