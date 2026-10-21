# Runtime library notices

License texts for libraries that may be included with the Python runtime.
The build also collects the interpreter, PyInstaller bootloader, pypdf and
certifi licenses from the dedicated build environment. macOS frameworks remain
system components and are not copied into the application.

These texts were copied from the distributions' installed license files:

- OpenSSL 3.6.4: Apache 2.0, https://github.com/openssl/openssl/blob/openssl-3.6.4/LICENSE.txt
- liblzma / XZ 5.8.3: COPYING overview and 0BSD text, https://github.com/tukaani-project/xz
- Zstandard 1.5.7: BSD alternative, https://github.com/facebook/zstd/blob/v1.5.7/LICENSE
- mpdecimal: BSD notice, https://www.bytereef.org/mpdecimal/

Recheck notices and library versions when changing the build interpreter.
