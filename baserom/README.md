# baserom

Put the stock MPK Mini Plus firmware here. It is not part of the repository
(it is copyrighted by inMusic Brands) and git ignores everything in this
folder except this file.

```bash
make baserom SRC=/path/to/MPK.exe     # the official updater
make baserom SRC=/path/to/130         # or the raw firmware file
```

The tool searches `SRC` for the reference firmware, checks its SHA-256
against [`config/baserom.sha256`](../config/baserom.sha256) and copies it to
`baserom/firmware.bin`. Other firmware versions are rejected for now.
