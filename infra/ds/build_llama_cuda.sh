#!/usr/bin/env bash
# Job de build (rede gerenciada): compila o llama.cpp com CUDA para a imagem dos jobs do Data Science.
# Os binários oficiais CUDA do llama.cpp exigem GLIBC 2.38, ausente nessa imagem. Compilamos o mesmo
# commit fixado pelo Rizzo Flow, com sysroot glibc 2.17, libstdc++ estática e CUDA 12.8 (sm_80/sm_86),
# no mesmo layout dos pacotes oficiais (backends como plug-ins, libs CUDA no mesmo diretório).
set -euo pipefail
COMMIT=161755f29e415e2c33efe906e91843c068efd664   # rizzo_flow.llama_release.COMMIT (b11081)
CODE="$(cd "$(dirname "$0")/../.." && pwd)"
BASE_PY=/opt/conda/bin/python3
TC="$HOME/toolchain"
OUT_NAME="llama-b11081-linux-x64-cuda-dsjobs"
OUT="$HOME/$OUT_NAME"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

echo "== glibc da imagem: $(ldd --version | head -1)"
/opt/conda/bin/conda create -q -y -p "$TC" -c conda-forge \
  "cuda-nvcc=12.8" "cuda-cudart-dev=12.8" "libcublas-dev=12.8" "cuda-version=12.8" \
  cmake ninja git "gxx_linux-64=13" "sysroot_linux-64=2.17" >/dev/null
export PATH="$TC/bin:$PATH" CUDAToolkit_ROOT="$TC" CUDACXX="$TC/bin/nvcc"
export CC="$TC/bin/x86_64-conda-linux-gnu-gcc" CXX="$TC/bin/x86_64-conda-linux-gnu-g++"

git clone -q https://github.com/ggml-org/llama.cpp /tmp/llama.cpp
git -C /tmp/llama.cpp checkout -q "$COMMIT"
cmake -S /tmp/llama.cpp -B /tmp/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON -DGGML_BACKEND_DL=ON -DGGML_NATIVE=OFF -DGGML_CPU_ALL_VARIANTS=ON \
  -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="80;86" -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_TOOLS=OFF \
  -DCMAKE_SHARED_LINKER_FLAGS="-static-libstdc++ -static-libgcc" \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DCMAKE_INSTALL_RPATH='$ORIGIN' -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
  >/tmp/cmake.log
# -k 0: alvos acessórios (apps) podem falhar; só as bibliotecas importam e são conferidas abaixo.
cmake --build /tmp/build -j "$(nproc)" -- -k 0 >/tmp/build.log 2>&1 || grep -E "^FAILED" /tmp/build.log || true
for lib in libllama.so libggml.so libggml-base.so libggml-cuda.so; do
  [ -f "/tmp/build/bin/$lib" ] || { echo "faltou $lib"; tail -40 /tmp/build.log; exit 1; }
done
ls /tmp/build/bin/libggml-cpu*.so >/dev/null || { echo "faltou backend de CPU"; exit 1; }

rm -rf "$OUT" && mkdir -p "$OUT"
find /tmp/build/bin -maxdepth 1 -name "*.so" -exec cp -L {} "$OUT/" \;
for lib in libcudart.so.12 libcublas.so.12 libcublasLt.so.12; do cp -L "$TC/lib/$lib" "$OUT/"; done
ls -la "$OUT"
echo "== dependências não resolvidas:"; for f in "$OUT"/*.so*; do LD_LIBRARY_PATH="$OUT" ldd "$f" | grep "not found" || true; done
echo "== maior GLIBC exigida:"; objdump -T "$OUT"/*.so* 2>/dev/null | grep -o "GLIBC_[0-9.]*" | sort -uV | tail -1

cd "$CODE"
TARBALL="/tmp/$OUT_NAME.tar.gz"
tar czf "$TARBALL" -C "$HOME" "$OUT_NAME"
OBJECT="runtimes/rizzo_flow/$OUT_NAME-$STAMP.tar.gz"
SHA="$("$BASE_PY" -m harness.objstore put dmb-artefatos "$OBJECT" "$TARBALL" --sha256)"
cat > /tmp/cuda-latest.json <<JSON
{"object": "$OBJECT", "sha256": "$SHA", "dir": "$OUT_NAME", "llama_commit": "$COMMIT",
 "cuda": "12.8", "archs": "80;86", "built_at": "$STAMP", "code_rev": "${DMB_CODE_REV:-}"}
JSON
"$BASE_PY" -m harness.objstore put dmb-artefatos runtimes/rizzo_flow/cuda-latest.json /tmp/cuda-latest.json
cat /tmp/cuda-latest.json
echo "== ok"
