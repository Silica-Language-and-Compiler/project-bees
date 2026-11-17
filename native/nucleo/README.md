# native/nucleo (placeholder: NUCLEO-L476RG, STM32L476RG, not written yet)

Platform id `nucleo`, `BEES_PLATFORM=nucleo`. No build exists; this directory only states what belongs here.

- TLS engine: Mbed TLS (not OpenSSL; contract/what-is-required-to-use.md, decision D40), configured here.
- `bees_platform_random.c`: the STM32L476RG hardware true random number generator (RNG peripheral, its clock enabled, the
  data-ready and seed/clock error flags checked on every word; a failed check is an error return, never a repeated word).
- `bees_platform_md5.c`: MD5 from Mbed TLS (`mbedtls_md5`), for BEAM mode's cookie handshake.
- `platform.mk`: the cross compiler (arm-none-eabi, Cortex-M4F) and flags, the same variables as `native/macos/platform.mk`.
