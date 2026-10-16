# Packaged sharp / libvips notices

This collection covers the two unchanged image-processing DLLs added to the
OpenMAIC Windows runtime in DeepSteam 2026.10.10-r3. It does not change the
interactive interface or assert that every application dependency was audited.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `libvips-42.dll` | 18614784 | `e6cc51bbc763e7deda536c6f56ce96b4c51ea769690ce4f4ed07607527b81dae` |
| `libvips-cpp-8.18.6.dll` | 333312 | `4f458afdb7b8a4290dbda3f287d7db037b239b8a9d21f0b87333f92192cdee76` |

The files come from the official npm package `@img/sharp-win32-x64@0.35.4`.
Its npm metadata declares **Apache-2.0 AND LGPL-3.0-or-later**. Copyright 2013
Lovell Fuller and others. Its unmodified package license, README, package
metadata and dependency-version list are retained here. The package README
and `sharp-libvips-THIRD-PARTY-NOTICES.md` preserve the upstream component
license table, including the LGPL libraries contained in the binary build.

`libvips-LGPL-2.1.txt` is the original license text in libvips 8.18.6. Upstream
libvips permits that version or later; the prebuilt sharp package identifies
its LGPL components as LGPLv3 under the later-version clause. Complete GNU
LGPL 3.0 and GPL 3.0 texts are therefore also included. These component
licenses remain applicable; DeepSteam branding does not replace them.

## Source and build information

The unmodified library and packaging source are available without charge:

- Official package and source revision: <https://registry.npmjs.org/@img%2Fsharp-win32-x64/0.35.4>,
  npm `gitHead` `7f1a0a22cc285fe180766f4935d50b55af6e8432`,
  <https://github.com/lovell/sharp/tree/7f1a0a22cc285fe180766f4935d50b55af6e8432>.
- libvips 8.18.6 source archive:
  <https://github.com/libvips/libvips/releases/download/v8.18.6/vips-8.18.6.tar.xz>,
  SHA-256 `3c41e1d5458081bfa4a5bc54e116c46259c75c6760a18027764555632b9dda3e`.
  The Windows build recipe specifies this same version and checksum.
- Windows source, patches and build recipes, pinned at
  `09cfccf20b91b441fbe97fa7a7ed8a597e55e830`:
  <https://github.com/libvips/build-win64-mxe/archive/09cfccf20b91b441fbe97fa7a7ed8a597e55e830.tar.gz>.
- The upstream sharp-libvips Windows packaging script identifies the official
  `vips-dev-x64-web-8.18.6-static.zip` input:
  <https://github.com/lovell/sharp-libvips/blob/v1.3.3-rc.0/build/win.sh>.
  Its dependency versions match the retained `sharp-package-versions.json`.
  The official Windows archive SHA-256 is
  `42ceea0c2f53d1244f3cb54c059881487b37452ee46c1c98c0d4b47480b20588`;
  its `libvips-42.dll` matches the packaged DLL byte for byte.

The build repositories contain the configuration and dependency source-fetch
recipes needed for the upstream library build. These source links are separate
from the runnable installer; no library source modifications were made here.
The exact notice-document URLs and their hashes are in `provenance.json`.

The Windows recipe clones the MXE `llvm-mingw-20260605` branch from
<https://github.com/kleisauke/mxe>. Its current official branch resolution is
`d973945bb92c7783d5afa41bb2b8d2e1a04eaba3`; the recipe itself fixes a branch
name, rather than an MXE commit. A fixed snapshot is available at
<https://github.com/kleisauke/mxe/archive/d973945bb92c7783d5afa41bb2b8d2e1a04eaba3.tar.gz>.
Its `download-vips-web` target fetches the dependency sources recursively and
checks the recipe hashes; `download-only-vips-web` fetches only libvips.

No single complete dependency-source archive is listed among the official
Windows release assets. The libvips source archive, Windows patches/build
recipes and MXE source-fetch recipes above are the upstream source-access
route. The notice collection checked those public entry points and the exact
libvips source checksum; it did not rebuild all DLL dependencies or claim that
a Windows-repository snapshot contains every dependency's source.

## Replacing the library

The LGPL libraries remain separate DLL files loaded by the native sharp
module. Stop DeepSteam before changing them. A recipient may build and use
compatible modified versions in place of these DLLs; preserve the filenames,
architecture and required interfaces. DeepSteam imposes no additional
restriction on modification or reverse engineering to debug changes to these
LGPL components. Re-running the installer can restore the distributed copies,
so keep modified library builds separately.

No classroom banner or chat attribution was added for this packaging repair.
Copyright, license texts, component notices and source access are supplied in
the distribution instead.
