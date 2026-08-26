cmake_minimum_required(VERSION 3.22.1)
project(myolo_detector)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ===== NCNN 预编译库配置（需用户手动放置）=====
# 1) 头文件：解压 ncnn 发布包后，把 include 目录放到 src/main/cpp/libncnn/include
set(NCNN_INCLUDE_DIR ${CMAKE_SOURCE_DIR}/libncnn/include)
# 2) 库文件：把 libncnn.so 放到 app/src/main/jniLibs/<abi>/libncnn.so
#    （即 ${CMAKE_SOURCE_DIR}/../jniLibs/${ANDROID_ABI}）
set(NCNN_LIB_DIR ${CMAKE_SOURCE_DIR}/../jniLibs/${ANDROID_ABI})

include_directories(${NCNN_INCLUDE_DIR})
link_directories(${NCNN_LIB_DIR})

# 目标库：native 实现
add_library(myolo_detector SHARED
    ncnn_detector.cpp
    jni_bridge.cpp
)

# 链接 ncnn 预编译库 + Android 系统库
target_link_libraries(myolo_detector
    ncnn
    log
    android
)
