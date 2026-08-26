# 混淆规则（默认关闭 minify，如需开启可在此添加）
# 保留 JNI 相关类，避免 native 方法被混淆
-keepclasseswithmembernames class com.myolo.pcontrol.inference.NcnnDetector {
    native <methods>;
}
