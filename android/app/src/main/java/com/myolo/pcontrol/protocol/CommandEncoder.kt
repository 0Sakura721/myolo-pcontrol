package com.myolo.pcontrol.protocol

import org.json.JSONObject

/**
 * 指令编码器：把检测结果 / 用户操作编码成 JSON。
 * 约定字段：
 * {
 *   "op": "move"|"click"|"scroll"|"drag"|"none",
 *   "x": 0.42, "y": 0.87,          // 归一化 0~1（仅 move/click/drag）
 *   "button": "left",               // 鼠标键（click/drag）
 *   "delta": -120,                  // 滚轮量（scroll）
 *   "t": 1711000000000             // 毫秒时间戳
 * }
 */
object CommandEncoder {

    fun encodeMove(cx: Float, cy: Float): JSONObject {
        val o = JSONObject()
        o.put("op", "move")
        o.put("x", cx.toDouble())
        o.put("y", cy.toDouble())
        o.put("t", System.currentTimeMillis())
        return o
    }

    fun encodeClick(x: Float, y: Float, button: String): JSONObject {
        val o = JSONObject()
        o.put("op", "click")
        o.put("x", x.toDouble())
        o.put("y", y.toDouble())
        o.put("button", button)
        o.put("t", System.currentTimeMillis())
        return o
    }

    fun encodeScroll(delta: Int): JSONObject {
        val o = JSONObject()
        o.put("op", "scroll")
        o.put("delta", delta)
        o.put("t", System.currentTimeMillis())
        return o
    }

    fun encodeDrag(x0: Float, y0: Float, x1: Float, y1: Float): JSONObject {
        val o = JSONObject()
        o.put("op", "drag")
        o.put("x", x0.toDouble())
        o.put("y", y0.toDouble())
        o.put("x2", x1.toDouble())
        o.put("y2", y1.toDouble())
        o.put("button", "left")
        o.put("t", System.currentTimeMillis())
        return o
    }

    fun encodeNone(): JSONObject {
        val o = JSONObject()
        o.put("op", "none")
        o.put("t", System.currentTimeMillis())
        return o
    }

    /**
     * 由检测结果生成 move 指令：取最高置信度目标框的中心作为目标点。
     * @param det detect 返回的 FloatArray，N*6 = [x1,y1,x2,y2,score,class]*N
     */
    fun encodeMoveByDetection(det: FloatArray): JSONObject {
        val stride = 6
        var bestScore = -1f
        var bestX1 = 0f; var bestY1 = 0f; var bestX2 = 0f; var bestY2 = 0f
        var i = 0
        while (i + stride <= det.size) {
            if (det[i + 4] > bestScore) {
                bestScore = det[i + 4]
                bestX1 = det[i]; bestY1 = det[i + 1]
                bestX2 = det[i + 2]; bestY2 = det[i + 3]
            }
            i += stride
        }
        if (bestScore < 0f) return encodeNone()
        val cx = (bestX1 + bestX2) / 2f
        val cy = (bestY1 + bestY2) / 2f
        return encodeMove(cx, cy)
    }
}
