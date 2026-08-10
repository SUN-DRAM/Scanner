# Weak cipher suites are enabled

TLS · High severity

## What it means

The server accepts one or more weak cipher suites — RC4, 3DES, NULL, EXPORT, or CBC-only suites, families of ciphers with known practical weaknesses.

## Why it matters

A weak cipher suite doesn't just sit there unused — if a client (or an attacker manipulating the handshake) offers it, the server will accept it. Depending on the specific cipher, this can allow an attacker on the network path to break the encryption or downgrade the connection to something they can read.

## How to fix it

Remove RC4, 3DES, NULL, EXPORT and CBC-only cipher suites from the server's TLS configuration, keeping modern AEAD suites (the ones TLS 1.2 and 1.3 use by default with ECDHE key exchange) only. Mozilla's SSL configuration generator is a reliable reference for a current, compatible cipher list.
