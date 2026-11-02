package esnet;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.interfaces.ECPrivateKey;
import java.security.interfaces.ECPublicKey;
import java.util.Base64;

/**
 * empty-serve milestone 4: the ServerToClientHandshake JWT (ES384), pure JDK, no external libs.
 *
 * Structure (from CloudburstMC/Protocol EncryptionUtils, Apache-2.0):
 *   header  {"alg":"ES384","x5u": base64(SPKI-DER of server public key)}
 *   payload {"salt": base64(16-byte token)}
 *   signingInput = b64url(header) + "." + b64url(payload)
 *   signature    = b64url( raw r||s of ECDSA-SHA384 )  (each coordinate 48 bytes)
 *   jwt          = signingInput + "." + signature
 *
 * The server puts this JWT in ServerToClientHandshakePacket (id 3). A real client validates it
 * against Mojang's chain; here we self-verify our own signature. UNVERIFIED against a live
 * client. Original code, MIT.
 */
public final class Handshake {

    public static String createJwt(KeyPair serverKeyPair, byte[] token) throws GeneralSecurityException {
        String x5u = Base64.getEncoder().encodeToString(serverKeyPair.getPublic().getEncoded());
        String header  = "{\"alg\":\"ES384\",\"x5u\":\"" + x5u + "\"}";
        String payload = "{\"salt\":\"" + Base64.getEncoder().encodeToString(token) + "\"}";
        String signingInput = b64url(header.getBytes(StandardCharsets.UTF_8))
                + "." + b64url(payload.getBytes(StandardCharsets.UTF_8));
        Signature sig = Signature.getInstance("SHA384withECDSA");
        sig.initSign(serverKeyPair.getPrivate());
        sig.update(signingInput.getBytes(StandardCharsets.UTF_8));
        byte[] der = sig.sign();
        return signingInput + "." + b64url(dErToRaw(der));
    }

    /** Verify a self-created ES384 JWT against the x5u public key it advertises. */
    public static boolean verify(String jwt) {
        try {
            String[] p = jwt.split("\\.");
            byte[] signing = (p[0] + "." + p[1]).getBytes(StandardCharsets.UTF_8);
            String headerJson = new String(Base64.getUrlDecoder().decode(p[0]), StandardCharsets.UTF_8);
            String x5u = headerJson.replaceAll(".*\"x5u\":\"([^\"]+)\".*", "$1");
            PublicKey pub = KeyFactory.getInstance("EC").generatePublic(
                    new java.security.spec.X509EncodedKeySpec(Base64.getDecoder().decode(x5u)));
            Signature v = Signature.getInstance("SHA384withECDSA");
            v.initVerify(pub);
            v.update(signing);
            return v.verify(rawToDError(Base64.getUrlDecoder().decode(p[2])));
        } catch (Exception e) {
            return false;
        }
    }

    public static byte[] extractSalt(String jwt) {
        String[] p = jwt.split("\\.");
        String payload = new String(Base64.getUrlDecoder().decode(p[1]), StandardCharsets.UTF_8);
        return Base64.getDecoder().decode(payload.replaceAll(".*\"salt\":\"([^\"]+)\".*", "$1"));
    }

    // DER ECDSA sig { INTEGER r, INTEGER s }  <->  raw r(48) || s(48)
    static byte[] dErToRaw(byte[] der) {
        BigInteger[] rs = decode(der);
        byte[] out = new byte[96];
        put384(rs[0], out, 0);
        put384(rs[1], out, 48);
        return out;
    }
    static byte[] rawToDError(byte[] raw) {
        byte[] r = trim(new byte[0], java.util.Arrays.copyOfRange(raw, 0, 48));
        byte[] s = trim(new byte[0], java.util.Arrays.copyOfRange(raw, 48, 96));
        return encode(r, s);
    }
    private static byte[] trim(byte[] x, byte[] v) {
        int i = 0; while (i < v.length - 1 && v[i] == 0) i++;
        byte[] t = java.util.Arrays.copyOfRange(v, i, v.length);
        if ((t[0] & 0x80) != 0) { byte[] w = new byte[t.length + 1]; System.arraycopy(t, 0, w, 1, t.length); t = w; }
        return t;
    }
    private static void put384(BigInteger n, byte[] out, int off) {
        byte[] b = n.toByteArray();
        int i = 0; while (i < b.length - 1 && b[i] == 0) i++;
        byte[] v = java.util.Arrays.copyOfRange(b, i, b.length);
        int start = off + (48 - v.length);
        System.arraycopy(v, 0, out, start < off ? off : start, v.length);
    }
    private static BigInteger[] decode(byte[] der) {
        int p = 2 + (der[1] == (byte) 0x81 ? 1 : 0); // skip SEQUENCE header
        p++;                                          // r INTEGER tag
        int rlen = der[p] & 0xff; p++;
        BigInteger r = new BigInteger(1, java.util.Arrays.copyOfRange(der, p, p + rlen)); p += rlen;
        p++; int slen = der[p] & 0xff; p++;
        BigInteger s = new BigInteger(1, java.util.Arrays.copyOfRange(der, p, p + slen));
        return new BigInteger[]{r, s};
    }
    private static byte[] encode(byte[] r, byte[] s) {
        int len = 2 + r.length + 2 + s.length;
        byte[] out = new byte[2 + len];
        int p = 0;
        out[p++] = 0x30; out[p++] = (byte) len;
        out[p++] = 0x02; out[p++] = (byte) r.length; System.arraycopy(r, 0, out, p, r.length); p += r.length;
        out[p++] = 0x02; out[p++] = (byte) s.length; System.arraycopy(s, 0, out, p, s.length);
        return out;
    }

    private static String b64url(byte[] b) { return Base64.getUrlEncoder().withoutPadding().encodeToString(b); }

    // --- self test ---
    public static void main(String[] args) throws Exception {
        boolean ok = true;
        KeyPair kp = Crypto.identityKeyPair();
        byte[] token = new byte[16]; new SecureRandom().nextBytes(token);
        String jwt = createJwt(kp, token);
        System.out.println("  jwt header.payload.sig parts = " + jwt.split("\\.").length);
        ok &= check("jwt has 3 dot-separated parts", jwt.split("\\.").length == 3);
        ok &= check("self-created jwt verifies", verify(jwt));
        ok &= check("salt round-trips through jwt", java.util.Arrays.equals(extractSalt(jwt), token));
        ok &= check("tampered jwt FAILS verify", !verify(jwt.substring(0, jwt.length() - 2) + "xx"));
        System.out.println(ok ? "\nRESULT: HANDSHAKE JWT OK" : "\nRESULT: HANDSHAKE FAILED");
        System.exit(ok ? 0 : 1);
    }
    private static boolean check(String n, boolean c) { System.out.println("  " + (c ? "PASS " : "FAIL ") + n); return c; }
}
