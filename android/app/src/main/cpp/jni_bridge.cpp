#include <jni.h>
#include <memory>
#include <vector>

#include "ncnn_detector.h"

// 全局检测器实例；绑定 Java 单例 com.myolo.pcontrol.inference.NcnnDetector
static std::unique_ptr<NcnnDetector> g_detector;

// JNI 异常检查辅助
static bool checkAndClear(JNIEnv* env, const char* msg) {
    if (env->ExceptionCheck()) {
        env->ExceptionClear();
        return false;
    }
    return true;
}

extern "C" {

// Java: external fun create(paramPath, binPath, useGpu): Boolean
JNIEXPORT jboolean JNICALL
Java_com_myolo_pcontrol_inference_NcnnDetector_create(
        JNIEnv* env, jobject /*thiz*/,
        jstring paramPath, jstring binPath, jboolean useGpu) {
    if (!paramPath || !binPath) {
        return JNI_FALSE;
    }
    const char* p = env->GetStringUTFChars(paramPath, nullptr);
    const char* b = env->GetStringUTFChars(binPath, nullptr);
    bool ok = false;
    if (p && b) {
        g_detector.reset(new NcnnDetector());
        ok = g_detector->load(p, b, useGpu == JNI_TRUE);
    }
    if (p) env->ReleaseStringUTFChars(paramPath, p);
    if (b) env->ReleaseStringUTFChars(binPath, b);
    return ok ? JNI_TRUE : JNI_FALSE;
}

// Java: external fun detect(rgba: ByteArray, width, height): FloatArray
// 返回 [x1,y1,x2,y2,score,class]*N，坐标已归一化到 0~1
JNIEXPORT jfloatArray JNICALL
Java_com_myolo_pcontrol_inference_NcnnDetector_detect(
        JNIEnv* env, jobject /*thiz*/,
        jbyteArray rgba, jint width, jint height) {
    if (!rgba) {
        return env->NewFloatArray(0);
    }
    jsize len = env->GetArrayLength(rgba);
    jbyte* buf = env->GetByteArrayElements(rgba, nullptr);

    std::vector<Box> boxes;
    if (buf && g_detector) {
        boxes = g_detector->detect(reinterpret_cast<const uint8_t*>(buf), width, height);
    }
    if (buf) {
        env->ReleaseByteArrayElements(rgba, buf, JNI_ABORT);
    }

    const int stride = 6; // x1,y1,x2,y2,score,cls
    jfloatArray result = env->NewFloatArray(static_cast<jsize>(boxes.size() * stride));
    if (result) {
        jfloat* out = env->GetFloatArrayElements(result, nullptr);
        if (out) {
            for (size_t i = 0; i < boxes.size(); ++i) {
                out[i * stride + 0] = boxes[i].x1;
                out[i * stride + 1] = boxes[i].y1;
                out[i * stride + 2] = boxes[i].x2;
                out[i * stride + 3] = boxes[i].y2;
                out[i * stride + 4] = boxes[i].score;
                out[i * stride + 5] = static_cast<jfloat>(boxes[i].cls);
            }
            env->ReleaseFloatArrayElements(result, out, 0);
        }
    }
    return result;
}

// Java: external fun destroy()
JNIEXPORT void JNICALL
Java_com_myolo_pcontrol_inference_NcnnDetector_destroy(
        JNIEnv* env, jobject /*thiz*/) {
    g_detector.reset();
}

} // extern "C"
