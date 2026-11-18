import base64
import re

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

html = open("/tmp/vb_3rd.html").read()
m = re.search(r"""<script[^>]*data-name=['"]crypto['"][^>]*data-value=['"]([^'"]+)['"]""", html)
print("crypto data found:", bool(m))
if m:
    print("ciphertext head:", m.group(1)[:60], "len:", len(m.group(1)))
keys = re.findall(r"""CryptoJS\.enc\.Utf8\.parse\(["']([^"']+)["']\)""", html)
print("keys/ivs in page:", keys)
key = "94588293375053432799222445521289".encode()
iv = "5259228356829423".encode()
raw = base64.b64decode(m.group(1))
cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
dec = cipher.decryptor()
plain = dec.update(raw) + dec.finalize()
pad = plain[-1]
plain = plain[:-pad]
print("decrypted:", plain.decode("utf-8", "replace"))
