# native/esp32s3 (placeholder: ESP32-S3, not written yet)

Platform id `esp32s3`, `BEES_PLATFORM=esp32s3`. No build exists; this directory only states what belongs here.

- TLS engine: Mbed TLS (not OpenSSL; contract/what-is-required-to-use.md, decision D40), configured by `platform.mk` and an
  `mbedtls_config` of this directory.
- `bees_platform_random.c`: the ESP32-S3 hardware RNG (`esp_fill_random` / `esp_random`) with its PHYSICAL ENTROPY SOURCE ENABLED
  (the RNG yields true random numbers only while the Wi-Fi or Bluetooth radio is on or `bootloader_random_enable()` has been
  called; this file enables that source and refuses to return bytes when it cannot).
- `bees_platform_md5.c`: MD5 from Mbed TLS (`mbedtls_md5`), for BEAM mode's cookie handshake.
- `platform.mk`: the cross compiler and flags, the same variables as `native/macos/platform.mk`.
