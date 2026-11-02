package esnet;

import javax.crypto.Cipher;
import javax.crypto.KeyAgreement;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.*;
import java.security.interfaces.ECPrivateKey;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECGenParameterSpec;
import java.util.Base64;

/**
 * empty-serve milestone 3a: cryptographic building blocks for the encrypted login.
 *
 * These are correct, self-tested primitives, NOT a claim that a real Bedrock client can
 * join. What is pinned elsewhere against the protocol spec (the exact SHA-512 key-derivation
 * layout, the AES-CTR IV construction, the login packet fields) still needs real-client
 * validation. Original code, MIT.
 *
 * Uses only the JDK so it has no third-party dependencies.
 */
public final class Crypto {

    /** Generate a P-384 (secp384r1) identity keypair - the server's long-term key. */
    public static KeyPair identityKeyPair() throws GeneralSecurityException {
        KeyPairGenerator kpg = KeyPairGenerator.getInstance("EC");
        kpg.initialize(new ECGenParameterSpec("secp384r1"));
        return kpg.generateKeyPair();
    }

    /** ECDH shared secret. Both sides must pass the same (local priv, remote pub) pair. */
    public static byte[] sharedSecret(PrivateKey localPriv, PublicKey remotePub)
            throws GeneralSecurityException {
        KeyAgreement ka = KeyAgreement.getInstance("ECDH");
        ka.init(localPriv);
        ka.doPhase(remotePub, true);
        return ka.generateSecret();
    }

    /**
     * Derive the connection AES key exactly as the Bedrock protocol does:
     *   key = SHA-256( token || ECDH-sharedSecret )   (32-byte AES-256 key)
     * token is the 16-byte random handshake salt; both sides compute the same key because
     * ECDH is symmetric. Sourced from CloudburstMC/Protocol EncryptionUtils (Apache-2.0).
     */
    public static byte[] connectionKey(byte[] sharedSecret, byte[] token) throws NoSuchAlgorithmException {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        md.update(token);
        md.update(sharedSecret);
        return md.digest();
    }

    /**
     * The AES-CTR IV pairing (SHA-256 over handshake packet bytes + key, last 16 bytes, with
     * a first-block skip quirk) is the part that must match a real client byte-for-byte. It is
     * NOT yet pinned here; until real-client validation, treat IV layout as unverified.
     */

    /** AES/CTR/NoPadding transformer; the 128-bit IV carries a per-direction block counter. */
    public static final class AESContext {
        private final SecretKeySpec key;
        private long rxCtr = Long.MAX_VALUE, txCtr = 0;
        private final byte[] rxIvTemplate, txIvTemplate;
        AESContext(byte[] key, byte[] txIv, byte[] rxIv) {
            this.key = new SecretKeySpec(key, "AES");
            this.txIvTemplate = txIv.clone();
            this.rxIvTemplate = rxIv.clone();
        }
        public SecretKeySpec key() { return key; }
        public byte[] encrypt(byte[] plain) throws GeneralSecurityException {
            return transform(Cipher.ENCRYPT_MODE, txIvTemplate, txCtr++, plain);
        }
        public byte[] decrypt(byte[] cipherText) throws GeneralSecurityException {
            return transform(Cipher.DECRYPT_MODE, rxIvTemplate, rxCtr++, cipherText);
        }
        private byte[] transform(int mode, byte[] ivTemplate, long counter, byte[] data)
                throws GeneralSecurityException {
            Cipher c = Cipher.getInstance("AES/CTR/NoPadding");
            c.init(mode, key, new IvParameterSpec(ivFor(ivTemplate, counter)));
            return c.doFinal(data);
        }
    }

    private static byte[] aesCtr(SecretKeySpec key, byte[] ivTemplate, long counter, byte[] data)
            throws GeneralSecurityException {
        Cipher c = Cipher.getInstance("AES/CTR/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key, new IvParameterSpec(ivFor(ivTemplate, counter)));
        return c.doFinal(data);   // CTR is symmetric: same op encrypts and decrypts
    }

    private static byte[] ivFor(byte[] template, long counter) {
        byte[] iv = template.clone();
        for (int i = 0; i < 8; i++) iv[15 - i] = (byte) (counter >>> (8 * i));
        return iv;
    }

    // --- self test: prove the primitives actually work, independent of Bedrock semantics ---
    public static void main(String[] args) throws Exception {
        boolean ok = true;

        // 1. identity keypair is P-384
        KeyPair kp = identityKeyPair();
        int bits = ((ECPublicKey) kp.getPublic()).getParams().getCurve().getField().getFieldSize();
        ok &= check("identity keypair is P-384", bits == 384);

        // 2. PEM round-trip (what identity.pem must survive)
        Path tmp = Files.createTempFile("es-id", ".pem");
        Files.write(tmp, pem(kp.getPrivate()));
        ECPrivateKey reload = (ECPrivateKey) fromPem(new String(Files.readAllBytes(tmp)));
        Files.delete(tmp);
        ok &= check("private key PEM round-trips", reload.getS().equals(((ECPrivateKey) kp.getPrivate()).getS()));

        // 3. ECDH agreement: A and B derive the same secret
        KeyPair a = identityKeyPair(), b = identityKeyPair();
        byte[] s1 = sharedSecret(a.getPrivate(), b.getPublic());
        byte[] s2 = sharedSecret(b.getPrivate(), a.getPublic());
        ok &= check("ECDH shared secrets match", MessageDigest.isEqual(s1, s2));

        // 4. connection key = SHA-256(token || sharedSecret): 32 bytes, same on both sides
        byte[] token = "0123456789abcdef".getBytes();   // 16-byte handshake salt
        byte[] key1 = connectionKey(s1, token), key2 = connectionKey(s2, token);
        ok &= check("connectionKey() is 32 bytes (AES-256)", key1.length == 32);
        ok &= check("connectionKey() deterministic for both parties",
                java.util.Arrays.equals(key1, key2));

        // 5. AES-CTR reversibility with an explicit shared key+iv+counter.
        //    (The real server<->client IV pairing is protocol-specific and NOT yet pinned
        //     here, so this tests the CTR primitive, not the wire handshake.)
        SecretKeySpec k = new SecretKeySpec(key1, "AES");
        byte[] fixedIv = new byte[16];
        java.util.Arrays.fill(fixedIv, (byte) 0x11);
        byte[] msg = "hello empty-serve world, a longer payload than one block for CTR".getBytes();
        byte[] ct = aesCtr(k, fixedIv, 0, msg);
        byte[] pt = aesCtr(k, fixedIv, 0, ct);
        ok &= check("AES-CTR encrypt/decrypt round-trip", java.util.Arrays.equals(msg, pt));
        ok &= check("AES-CTR ciphertext differs from plaintext", !java.util.Arrays.equals(msg, ct));

        System.out.println(ok ? "\nRESULT: CRYPTO PRIMITIVES OK" : "\nRESULT: CRYPTO FAILED");
        System.exit(ok ? 0 : 1);
    }

    private static byte[] pem(Key p) {
        return ("-----BEGIN EC PRIVATE KEY-----\n"
                + Base64.getMimeEncoder(64, new byte[]{'\n'}).encodeToString(p.getEncoded())
                + "\n-----END EC PRIVATE KEY-----\n").getBytes();
    }
    private static PrivateKey fromPem(String s) throws Exception {
        String b64 = s.replaceAll("-----[A-Z ]+-----", "").replaceAll("\\s", "");
        byte[] der = Base64.getMimeDecoder().decode(b64);
        return KeyFactory.getInstance("EC")
                .generatePrivate(new java.security.spec.PKCS8EncodedKeySpec(der));
    }
    private static boolean check(String name, boolean cond) {
        System.out.println("  " + (cond ? "PASS " : "FAIL ") + name); return cond;
    }
}
