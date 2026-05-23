# Build prover_cli / verifier_cli against a pre-built Longfellow checkout.
#
#   cmake -DLONGFELLOW_ROOT=$(realpath ../longfellow-zk) -S . -B build
#   cmake --build build -j

cmake_minimum_required(VERSION 3.16)
project(anonymous_review_prover CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED LONGFELLOW_ROOT)
  message(FATAL_ERROR
    "Set -DLONGFELLOW_ROOT=/path/to/google/longfellow-zk checkout")
endif()

set(LF_LIB_DIR "${LONGFELLOW_ROOT}/lib")
set(LF_BUILD_DIR "${LONGFELLOW_ROOT}/build" CACHE PATH "Longfellow build dir")

# Longfellow ships a single bundled archive that contains every dependency
# its mdoc_zk C API needs.
set(LF_STATIC "${LF_BUILD_DIR}/circuits/mdoc/libmdoc_static.a")
if(NOT EXISTS "${LF_STATIC}")
  message(FATAL_ERROR "Missing ${LF_STATIC}; build Longfellow first")
endif()

include_directories(${LF_LIB_DIR})

find_package(OpenSSL REQUIRED)

# Locate zstd via pkg-config (preferred) or as a bare library.
find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
  pkg_check_modules(ZSTD QUIET libzstd)
endif()
if(NOT ZSTD_FOUND)
  find_library(ZSTD_LIB zstd REQUIRED)
endif()

set(_zstd_target ${ZSTD_LIBRARIES})
if(NOT _zstd_target)
  set(_zstd_target ${ZSTD_LIB})
endif()

foreach(_cli prover_cli verifier_cli)
  add_executable(${_cli} src/${_cli}.cc)
  target_link_libraries(${_cli} PRIVATE
    ${LF_STATIC}
    OpenSSL::Crypto
    ${_zstd_target}
  )
  if(ZSTD_INCLUDE_DIRS)
    target_include_directories(${_cli} PRIVATE ${ZSTD_INCLUDE_DIRS})
  endif()
  if(ZSTD_LIBRARY_DIRS)
    target_link_directories(${_cli} PRIVATE ${ZSTD_LIBRARY_DIRS})
  endif()
endforeach()
