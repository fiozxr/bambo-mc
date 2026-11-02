package esnet;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.List;

/**
 * empty-serve milestone 3b: Bedrock in-game packet framing + unsigned varint codec.
 *
 * After the connection handshake, every game datagram is wrapped as:
 *   0xFE 0xAD | 24-bit little-endian length | 24-bit sequence | 8-bit reliability | N inner packets
 * where each inner packet is  [unsigned varint length][packet bytes].
 *
 * The inner packets themselves later get AES-CTR'd (that's Crypto's job once the IV pairing
 * is pinned to spec). This class is pure framing, so it is verifiable on its own.
 * Original code, MIT.
 */
public final class Framing {

    static final short FRAME_MAGIC = (short) 0xfead; // written little-endian => AD FE? see encode

    /** Encode one outbound frame carrying N inner packets, with a given sequence number. */
    public static byte[] encodeFrame(long sequence, byte[][] innerPackets) {
        ByteArrayOutputStream payload = new ByteArrayOutputStream();
        for (byte[] p : innerPackets) {
            byte[] len = writeVarInt(p.length);
            payload.write(len, 0, len.length);
            payload.write(p, 0, p.length);
        }
        byte[] body = payload.toByteArray();

        // length covers sequence(3) + reliability(1) + body
        int datagramLen = 3 + 1 + body.length;
        byte[] frame = new byte[2 + 3 + 3 + 1 + body.length];
        ByteBuffer b = ByteBuffer.wrap(frame).order(ByteOrder.LITTLE_ENDIAN);
        b.put((byte) 0xfe); b.put((byte) 0xad);
        putUInt24(b, datagramLen);
        putUInt24(b, (int) (sequence & 0xffffff));
        b.put((byte) 0x00);               // reliability: 0 = unreliable (framing test value)
        b.put(body);
        return frame;
    }

    /** Decode a frame into its sequence number and inner packets, or null if not a frame. */
    public static Frame decodeFrame(byte[] data) {
        if (data.length < 9 || (data[0] & 0xff) != 0xfe || (data[1] & 0xff) != 0xad) return null;
        ByteBuffer b = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        b.position(2);
        int datagramLen = readUInt24(b);
        int sequence = readUInt24(b);
        int reliability = b.get() & 0xff;

        int end = Math.min(data.length, 2 + 3 + datagramLen); // 2 magic + 3 len + datagram body
        List<byte[]> packets = new ArrayList<>();
        while (b.position() < end) {
            long[] res = readVarInt(b);
            int len = (int) res[0];
            if (res[1] < 0 || b.position() + len > end) break; // malformed/truncated
            byte[] p = new byte[len];
            b.get(p);
            packets.add(p);
        }
        return new Frame(sequence, reliability, packets.toArray(new byte[0][]));
    }

    public record Frame(long sequence, int reliability, byte[][] packets) {}

    // --- unsigned varint (LEB128, 7 bits per byte, Bedrock flavour) ---
    public static byte[] writeVarInt(int value) {
        ByteArrayOutputStream o = new ByteArrayOutputStream(5);
        long v = value & 0xffffffffL;
        do {
            int b = (int) (v & 0x7f);
            v >>>= 7;
            if (v != 0) b |= 0x80;
            o.write(b);
        } while (v != 0);
        return o.toByteArray();
    }

    /** Returns {decodedValue, bytesConsumed}. */
    public static long[] readVarInt(ByteBuffer b) {
        int start = b.position();
        long value = 0; int size = 0; byte current;
        do {
            if (!b.hasRemaining()) return new long[]{0, -1};
            current = b.get();
            value |= ((long) (current & 0x7f)) << (size * 7);
            size++;
        } while ((current & 0x80) != 0 && size < 5);
        return new long[]{value & 0xffffffffL, size};
    }

    static void putUInt24(ByteBuffer b, int v) {
        b.put((byte) (v & 0xff)); b.put((byte) ((v >> 8) & 0xff)); b.put((byte) ((v >> 16) & 0xff));
    }
    static int readUInt24(ByteBuffer b) {
        return (b.get() & 0xff) | ((b.get() & 0xff) << 8) | ((b.get() & 0xff) << 16);
    }

    // --- self test ---
    public static void main(String[] args) {
        boolean ok = true;
        byte[] p1 = new byte[]{0x01, 0x02, 0x03, 0x04};                 // some packet
        byte[] p2 = new byte[300]; java.util.Arrays.fill(p2, (byte) 0x7f); // forces 2-byte varint len
        byte[] frame = encodeFrame(42, new byte[][]{p1, p2});

        ok &= check("frame starts with 0xfe 0xad", (frame[0] & 0xff) == 0xfe && (frame[1] & 0xff) == 0xad);
        Frame d = decodeFrame(frame);
        ok &= check("decodes as a frame", d != null);
        ok &= check("sequence round-trips (42)", d != null && d.sequence() == 42);
        ok &= check("two inner packets recovered", d != null && d.packets().length == 2);
        ok &= check("packet 1 intact", d != null && java.util.Arrays.equals(d.packets()[0], p1));
        ok &= check("packet 2 intact (300B, multi-byte varint)", d != null && java.util.Arrays.equals(d.packets()[1], p2));

        // varint edge cases
        for (int v : new int[]{0, 1, 127, 128, 300, 16383, 16384, 0x7fffffff}) {
            ByteBuffer bb = ByteBuffer.wrap(writeVarInt(v)).order(ByteOrder.LITTLE_ENDIAN);
            long back = readVarInt(bb)[0];
            ok &= check("varint " + v + " round-trips", back == (v & 0xffffffffL));
        }

        System.out.println(ok ? "\nRESULT: FRAMING + VARINT OK" : "\nRESULT: FRAMING FAILED");
        System.exit(ok ? 0 : 1);
    }
    private static boolean check(String n, boolean c) { System.out.println("  " + (c ? "PASS " : "FAIL ") + n); return c; }
}
