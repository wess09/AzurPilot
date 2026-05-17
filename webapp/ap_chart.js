(function () {
    function setTooltipContent(tipEl, rows) {
        if (!tipEl || !Array.isArray(rows)) return;
        while (tipEl.firstChild) {
            tipEl.removeChild(tipEl.firstChild);
        }
        rows.forEach(function (row) {
            if (!row) return;
            var div = document.createElement('div');
            if (row.style && typeof row.style === 'object') {
                Object.keys(row.style).forEach(function (k) {
                    div.style[k] = row.style[k];
                });
            }
            if (row.parts && Array.isArray(row.parts)) {
                row.parts.forEach(function (part) {
                    if (!part) return;
                    if (part.type === 'text') {
                        var span = document.createElement('span');
                        span.textContent = part.value != null ? String(part.value) : '';
                        if (part.style && typeof part.style === 'object') {
                            Object.keys(part.style).forEach(function (k) {
                                span.style[k] = part.style[k];
                            });
                        }
                        div.appendChild(span);
                    } else if (part.type === 'bold') {
                        var b = document.createElement('b');
                        b.textContent = part.value != null ? String(part.value) : '';
                        if (part.style && typeof part.style === 'object') {
                            Object.keys(part.style).forEach(function (k) {
                                b.style[k] = part.style[k];
                            });
                        }
                        div.appendChild(b);
                    }
                });
            }
            tipEl.appendChild(div);
        });
    }

    var chartType = "__CHART_TYPE__";
    var labels = __LABELS__;
    var opens = __OPENS__;
    var highs = __HIGHS__;
    var lows = __LOWS__;
    var closes = __CLOSES__;
    var counts = __COUNTS__;
    var ap = __AP__;
    var apTs = __AP_TS__;
    var avg = __AVG__;
    var isDetailMode = __IS_DETAIL_MODE__;
    var sources = __SOURCES__;
    var yellowCoins = __YELLOW_COINS__;
    var purpleCoins = __PURPLE_COINS__;
    var coinsSources = __COINS_SOURCES__;
    var showCoins = __SHOW_COINS__;
    var lineVirtualAsset = __VIRTUAL_ASSET__;
    var lineVirtualAssetTs = __VIRTUAL_ASSET_TS__;
    var hasVirtualAssetSeries = lineVirtualAsset && lineVirtualAsset.length > 0;
    var lineAsset = __ASSET__;
    var lineAssetTs = __ASSET_TS__;
    var hasAssetSeries = lineAsset && lineAsset.length > 0;
    var lineDistance = __DISTANCE__;
    var hasDistanceSeries = lineDistance && lineDistance.length > 0;

    var nn = chartType === 'line' ? ap.length : labels.length;
    if (nn < 1) return;

    var chartId = "__CHART_ID__";
    var cv = document.getElementById(chartId);
    if (!cv) return;
    var tipEl = document.getElementById(chartId + "_tip");
    var ovCv = document.getElementById(chartId + "_ov");

    var dpr = window.devicePixelRatio || 1;
    var W, H, pad, gW, gH;

    // 延迟渲染以确保 canvas 布局完成，避免首次加载坐标偏移
    requestAnimationFrame(function () {
        initChart();
    });

    function initChart() {
        W = cv.clientWidth;
        H = cv.clientHeight;
        if (!W || !H) { W = cv.parentElement.clientWidth || 800; H = 360; }
        cv.width = W * dpr; cv.height = H * dpr;
        cv.style.width = W + "px"; cv.style.height = H + "px";
        ovCv.width = W * dpr; ovCv.height = H * dpr;
        ovCv.style.width = W + "px"; ovCv.style.height = H + "px";

        var ctx = cv.getContext("2d");
        ctx.scale(dpr, dpr);
        var oc = ovCv.getContext("2d");

        // 硬币刻度标签布局常量
        var COIN_TICK_X = 8;
        var COIN_TICK_BASELINE = 4;
        var COIN_TICK_STACK_GAP = 11;

        pad = { t: 20, r: showCoins ? 110 : 20, b: 52, l: 52 };
        gW = W - pad.l - pad.r;
        gH = H - pad.t - pad.b;

        // ---- 主数据范围（体力轴，最小值固定 0） ----
        var allMin = 0, allMax = -Infinity;
        if (chartType === 'line') {
            for (var i = 0; i < nn; i++) {
                if (ap[i] > allMax) allMax = ap[i];
            }
        } else {
            for (var i = 0; i < nn; i++) {
                if (highs[i] > allMax) allMax = highs[i];
            }
        }
        if (allMax === -Infinity) allMax = 100;
        var allRng = allMax - allMin || 1;
        allMax += allRng * 0.08;

        // ---- 黄币独立范围 ----
        var yellowMin = Infinity, yellowMax = -Infinity;
        var yellowCoinsLen = yellowCoins ? yellowCoins.length : 0;
        var hasYellowCoins = showCoins && chartType === 'line' && yellowCoinsLen > 0;
        if (hasYellowCoins) {
            for (var i = 0; i < yellowCoinsLen; i++) {
                if (yellowCoins[i] === null || yellowCoins[i] === undefined) continue;
                if (yellowCoins[i] < yellowMin) yellowMin = yellowCoins[i];
                if (yellowCoins[i] > yellowMax) yellowMax = yellowCoins[i];
            }
            if (yellowMin === Infinity) yellowMin = 0;
            if (yellowMax === -Infinity) yellowMax = 1000;
            var yellowRng = yellowMax - yellowMin || 1;
            yellowMin -= yellowRng * 0.08;
            yellowMax += yellowRng * 0.08;
        }

        // ---- 紫币独立范围（最小值固定 0） ----
        var purpleMin = 0, purpleMax = -Infinity;
        var purpleCoinsLen = purpleCoins ? purpleCoins.length : 0;
        var hasPurpleCoins = showCoins && chartType === 'line' && purpleCoinsLen > 0;
        if (hasPurpleCoins) {
            for (var i = 0; i < purpleCoinsLen; i++) {
                if (purpleCoins[i] === null || purpleCoins[i] === undefined) continue;
                if (purpleCoins[i] > purpleMax) purpleMax = purpleCoins[i];
            }
            if (purpleMax === -Infinity) purpleMax = 1000;
            var purpleRng = purpleMax - purpleMin || 1;
            purpleMax += purpleRng * 0.08;
        }

        // ---- 紫币独立轴 ----
        var hasPurpleAxis = showCoins && chartType === 'line' && hasPurpleCoins;
        // ---- 组合轴（黄币 + 虚拟资产 + 资产共用） ----
        var hasCombined = showCoins && chartType === 'line' && (hasYellowCoins || hasVirtualAssetSeries || hasAssetSeries || hasDistanceSeries);
        var hasExtra = hasPurpleAxis || hasCombined;
        var combinedMin = 0, combinedMax = -Infinity;
        function scanRange(arr) {
            for (var i = 0; i < arr.length; i++) {
                if (arr[i] === null || arr[i] === undefined) continue;
                if (arr[i] > combinedMax) combinedMax = arr[i];
            }
        }
        if (hasCombined) {
            if (hasYellowCoins) scanRange(yellowCoins);
            if (hasVirtualAssetSeries) scanRange(lineVirtualAsset);
            if (hasAssetSeries) scanRange(lineAsset);
            if (hasDistanceSeries) scanRange(lineDistance);
            if (combinedMax === -Infinity) combinedMax = 1000;
            var combinedRng = combinedMax - combinedMin || 1;
            combinedMax += combinedRng * 0.08;
        }

        // 刻度配置（右侧标签）：第1行紫币独立，第2行黄币代表合并轴
        var EXTRA_SERIES_CONFIGS = [];
        var cfgOffset = 0;
        function addCfg(has, color, dataMin, dataMax) {
            if (!has) return;
            EXTRA_SERIES_CONFIGS.push({ color: color, dataMin: dataMin, dataMax: dataMax, offsetY: cfgOffset });
            cfgOffset += COIN_TICK_STACK_GAP;
        }
        addCfg(hasPurpleCoins, "#ce93d8", purpleMin, purpleMax);
        addCfg(hasCombined, "#ffd54f", combinedMin, combinedMax);

        // 系列绘制配置（所有线都要画，虚拟/资产用时间戳）
        var SERIES_DRAW = [
            { has: hasPurpleCoins, data: purpleCoins, yFn: yOfPurple, dash: [4, 2] },
            { has: hasYellowCoins, data: yellowCoins, yFn: yOfCombined, dash: [4, 2] },
            { has: hasVirtualAssetSeries, data: lineVirtualAsset, ts: lineVirtualAssetTs, yFn: yOfCombined, dash: [5, 3] },
            { has: hasAssetSeries, data: lineAsset, ts: lineAssetTs, yFn: yOfCombined, dash: [5, 3] },
            { has: hasDistanceSeries, data: lineDistance, yFn: yOfCombined, dash: [] }
        ];

        // Y 坐标映射
        function yScale(value, rangeMin, rangeMax) {
            return pad.t + gH - (value - rangeMin) / (rangeMax - rangeMin) * gH;
        }
        function yOf(v) { return yScale(v, allMin, allMax); }
        function yOfPurple(v) { return yScale(v, purpleMin, purpleMax); }
        function yOfCombined(v) { return yScale(v, combinedMin, combinedMax); }

        // 时间感知的 x 坐标映射
        function xOfLine(i) {
            if (chartType === 'line' && apTs && apTs.length === nn && nn > 1) {
                var minT = apTs[0], maxT = apTs[nn - 1];
                var tr = maxT - minT || 1;
                return pad.l + ((apTs[i] - minT) / tr) * gW;
            }
            return pad.l + (i / Math.max(nn - 1, 1)) * gW;
        }

        function drawAssetTicks(ctx, yOfMain, mainMin, mainMax) {
            if (!hasExtra) return;
            ctx.font = "10px -apple-system, sans-serif";
            ctx.textAlign = "left";
            for (var i = 0; i <= 5; i++) {
                var mainVal = mainMin + (mainMax - mainMin) * (i / 5);
                var y = yOfMain(mainVal);
                for (var ci = 0; ci < EXTRA_SERIES_CONFIGS.length; ci++) {
                    var cfg = EXTRA_SERIES_CONFIGS[ci];
                    var val = cfg.dataMin + (cfg.dataMax - cfg.dataMin) * (i / 5);
                    ctx.fillStyle = cfg.color;
                    ctx.fillText(Math.round(val), W - pad.r + COIN_TICK_X, y + COIN_TICK_BASELINE + cfg.offsetY);
                }
            }
        }

        // ---- 绘制系列线（紫币独立 Y 轴，黄币/虚拟资产/资产共用组合 Y 轴） ----
        function drawSeriesLine(xOf, start, end) {
            for (var ci = 0; ci < SERIES_DRAW.length; ci++) {
                var sd = SERIES_DRAW[ci];
                if (!sd.has) continue;

                ctx.lineWidth = 1.5;
                ctx.lineJoin = "round";
                ctx.setLineDash(sd.dash);
                ctx.strokeStyle = ["#ce93d8", "#ffd54f", "#4fc3f7", "#81c784", "#1565c0"][ci];
                ctx.beginPath();
                var started = false;

                if (sd.ts && apTs && apTs.length === nn && nn > 1) {
                    var minT = apTs[Math.max(0, start)];
                    var maxT = apTs[Math.max(0, Math.min(nn - 1, end - 1))];
                    var tr = maxT - minT || 1;
                    for (var j = 0; j < sd.ts.length; j++) {
                        if (sd.ts[j] < minT || sd.ts[j] > maxT) continue;
                        var dv = sd.data[j];
                        if (dv === null || dv === undefined) { started = false; continue; }
                        var px = pad.l + ((sd.ts[j] - minT) / tr) * gW;
                        var py = sd.yFn(dv);
                        if (!started) { ctx.moveTo(px, py); started = true; }
                        else { ctx.lineTo(px, py); }
                    }
                } else {
                    for (var i = start; i < end && i < sd.data.length; i++) {
                        if (sd.data[i] === null || sd.data[i] === undefined) { started = false; continue; }
                        var x = xOf(i), y = sd.yFn(sd.data[i]);
                        if (!started) { ctx.moveTo(x, y); started = true; }
                        else { ctx.lineTo(x, y); }
                    }
                }
                ctx.stroke();
            }
            ctx.setLineDash([]);
        }

        var candleSpace = gW / nn;
        var candleW = Math.max(3, Math.min(candleSpace * 0.6, 30));
        function xCenter(i) { return pad.l + candleSpace * (i + 0.5); }

        // ======== 初始绘制（非缩放全量视图） ========
        ctx.fillStyle = "#1a1a2e";
        ctx.fillRect(0, 0, W, H);

        ctx.strokeStyle = "#2a2a3e";
        ctx.lineWidth = 1;
        ctx.fillStyle = "#666";
        ctx.font = "11px -apple-system, sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (var i = 0; i <= 5; i++) {
            var v = allMin + (allMax - allMin) * (i / 5);
            var y = yOf(v);
            ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
            ctx.fillText(Math.round(v), pad.l - 8, y);
        }

        drawAssetTicks(ctx, yOf, allMin, allMax);

        var avgY = yOf(avg);
        ctx.save();
        ctx.strokeStyle = "#ff9800";
        ctx.lineWidth = 1;
        ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(pad.l, avgY); ctx.lineTo(W - pad.r, avgY); ctx.stroke();
        ctx.restore();
        ctx.fillStyle = "#ff9800";
        ctx.font = "10px -apple-system, sans-serif";
        ctx.textAlign = "right";
        ctx.fillText("均值:" + avg, W - pad.r - 4, avgY - 8);

        ctx.fillStyle = "#666";
        ctx.font = "10px -apple-system, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        if (chartType === 'line') {
            var labelStep = Math.max(1, Math.floor(nn / 8));
            for (var i = 0; i < nn; i += labelStep) {
                ctx.save();
                ctx.translate(xOfLine(i), H - pad.b + 8);
                ctx.rotate(0.4);
                ctx.fillText(labels[i], 0, 0);
                ctx.restore();
            }
        } else {
            var labelStep = Math.max(1, Math.floor(nn / 12));
            for (var i = 0; i < nn; i += labelStep) {
                ctx.fillText(labels[i], xCenter(i), H - pad.b + 8);
            }
        }

        if (chartType === 'line') {
            var grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + gH);
            grad.addColorStop(0, "rgba(100,120,160,0.18)");
            grad.addColorStop(1, "rgba(100,120,160,0.02)");
            ctx.beginPath();
            ctx.moveTo(xOfLine(0), yOf(ap[0]));
            for (var i = 1; i < nn; i++) {
                if (nn < 30) {
                    var x0 = xOfLine(i - 1), y0 = yOf(ap[i - 1]), x1 = xOfLine(i), y1 = yOf(ap[i]);
                    var cpx = (x0 + x1) / 2;
                    ctx.bezierCurveTo(cpx, y0, cpx, y1, x1, y1);
                } else {
                    ctx.lineTo(xOfLine(i), yOf(ap[i]));
                }
            }
            ctx.lineTo(xOfLine(nn - 1), pad.t + gH);
            ctx.lineTo(xOfLine(0), pad.t + gH);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();

            ctx.lineWidth = 2;
            ctx.lineJoin = "round";
            for (var i = 1; i < nn; i++) {
                ctx.beginPath();
                ctx.moveTo(xOfLine(i - 1), yOf(ap[i - 1]));
                var segmentColor = ap[i] >= ap[i - 1] ? "#ef5350" : "#26a69a";
                ctx.strokeStyle = segmentColor;
                if (nn < 30) {
                    var x0 = xOfLine(i - 1), y0 = yOf(ap[i - 1]), x1 = xOfLine(i), y1 = yOf(ap[i]);
                    var cpx = (x0 + x1) / 2;
                    ctx.bezierCurveTo(cpx, y0, cpx, y1, x1, y1);
                } else {
                    ctx.lineTo(xOfLine(i), yOf(ap[i]));
                }
                ctx.stroke();
            }
            if (nn < 60) {
                for (var i = 0; i < nn; i++) {
                    ctx.beginPath();
                    ctx.arc(xOfLine(i), yOf(ap[i]), 3.5, 0, Math.PI * 2);
                    var dotColor = (i > 0 && ap[i] < ap[i - 1]) ? "#26a69a" : "#ef5350";
                    ctx.fillStyle = dotColor;
                    ctx.fill();
                    ctx.strokeStyle = "#1a1a2e";
                    ctx.lineWidth = 1.5;
                    ctx.stroke();
                }
            }
        } else {
            for (var i = 0; i < nn; i++) {
                var cx = xCenter(i);
                var o = opens[i], h = highs[i], l = lows[i], c = closes[i];
                var isUp = c > o;
                var isDown = c < o;
                var isFlat = c === o;
                var color = isFlat ? "#888" : (isUp ? "#ef5350" : "#26a69a");

                ctx.strokeStyle = color;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(cx, yOf(h));
                ctx.lineTo(cx, yOf(l));
                ctx.stroke();

                var bodyTop = yOf(Math.max(o, c));
                var bodyBot = yOf(Math.min(o, c));
                var bodyH = Math.max(bodyBot - bodyTop, 1);

                if (isUp || isDown) {
                    ctx.fillStyle = color;
                    ctx.fillRect(cx - candleW / 2, bodyTop, candleW, bodyH);
                } else {
                    ctx.beginPath();
                    ctx.moveTo(cx - candleW / 2, yOf(o));
                    ctx.lineTo(cx + candleW / 2, yOf(o));
                    ctx.stroke();
                }
            }

            function drawMA(days, maColor) {
                if (nn < days) return;
                ctx.beginPath();
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = maColor;
                var started = false;
                for (var i = days - 1; i < nn; i++) {
                    var sum = 0;
                    for (var j = 0; j < days; j++) sum += closes[i - j];
                    var maVal = sum / days;
                    var x = xCenter(i), y = yOf(maVal);
                    if (!started) { ctx.moveTo(x, y); started = true; }
                    else { ctx.lineTo(x, y); }
                }
                ctx.stroke();
            }
            drawMA(5, "#ffeb3b");
            drawMA(10, "#e91e63");
        }

        // 绘制额外系列线（黄币/紫币/虚拟资产/资产）
        drawSeriesLine(xOfLine, 0, nn);

        // ======== 鼠标交互：十字线 + 滚珠 + 提示框 ========
        cv.addEventListener("mousemove", function (e) {
            var rect = cv.getBoundingClientRect();
            var mx_ = e.clientX - rect.left;
            var my_ = e.clientY - rect.top;

            oc.setTransform(1, 0, 0, 1, 0, 0);
            oc.clearRect(0, 0, ovCv.width, ovCv.height);

            if (mx_ < pad.l || mx_ > W - pad.r || my_ < pad.t || my_ > pad.t + gH) {
                tipEl.style.display = "none";
                return;
            }

            oc.scale(dpr, dpr);

            if (chartType === 'line') {
                var visibleStart = Math.max(0, Math.floor(panOffset));
                var visibleCount = Math.ceil(nn / zoomLevel);
                var visibleEnd = Math.min(nn, visibleStart + visibleCount);
                var visibleNn = visibleEnd - visibleStart;

                var dMin = 0, dMax = -Infinity;
                for (var i = visibleStart; i < visibleEnd; i++) {
                    if (ap[i] > dMax) dMax = ap[i];
                }
                if (dMax === -Infinity) dMax = 100;
                var drng = dMax - dMin || 1;
                dMax += drng * 0.1;

                var xScale = gW / Math.max(visibleNn - 1, 1);

                // 时间感知的鼠标索引定位
                var idx = 0;
                if (apTs && apTs.length === nn && visibleEnd > visibleStart) {
                    var ratio = (mx_ - pad.l) / gW;
                    var minT = apTs[visibleStart];
                    var maxT = apTs[Math.max(0, visibleEnd - 1)];
                    var targetTs = minT + ratio * (maxT - minT);
                    var closestDist = Infinity;
                    idx = visibleStart;
                    for (var i = visibleStart; i < visibleEnd; i++) {
                        var dist = Math.abs(apTs[i] - targetTs);
                        if (dist < closestDist) { closestDist = dist; idx = i; }
                    }
                } else {
                    idx = Math.round(visibleStart + (mx_ - pad.l) / xScale);
                }
                idx = Math.max(0, Math.min(nn - 1, idx));

                // 时间感知的十字线 x 位置
                var px;
                if (apTs && apTs.length === nn && visibleEnd > visibleStart) {
                    var minT = apTs[visibleStart];
                    var maxT = apTs[Math.max(0, visibleEnd - 1)];
                    var tr = maxT - minT || 1;
                    px = pad.l + ((apTs[idx] - minT) / tr) * gW;
                } else {
                    px = pad.l + (idx - visibleStart) * xScale;
                }
                var py = yScale(ap[idx], dMin, dMax);

                oc.strokeStyle = "rgba(255,255,255,0.18)";
                oc.lineWidth = 1;
                oc.setLineDash([4, 3]);
                oc.beginPath(); oc.moveTo(px, pad.t); oc.lineTo(px, pad.t + gH); oc.stroke();
                oc.beginPath(); oc.moveTo(pad.l, py); oc.lineTo(W - pad.r, py); oc.stroke();
                oc.setLineDash([]);

                oc.beginPath(); oc.arc(px, py, 6, 0, Math.PI * 2);
                oc.fillStyle = "rgba(100,181,246,0.3)"; oc.fill();
                oc.beginPath(); oc.arc(px, py, 4, 0, Math.PI * 2);
                oc.fillStyle = "#64b5f6"; oc.fill();
                oc.strokeStyle = "#fff"; oc.lineWidth = 2; oc.stroke();

                // ---- 滚珠：紫币（独立轴）+ 黄币/虚拟资产/资产（共用轴） ----
                function hexToRgba(hex, alpha) {
                    var r = parseInt(hex.slice(1, 3), 16);
                    var g = parseInt(hex.slice(3, 5), 16);
                    var b = parseInt(hex.slice(5, 7), 16);
                    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
                }
                function drawBead(val, color, yFn) {
                    var by = yFn(val);
                    oc.beginPath(); oc.arc(px, by, 5, 0, Math.PI * 2);
                    oc.fillStyle = hexToRgba(color, 0.3); oc.fill();
                    oc.beginPath(); oc.arc(px, by, 3, 0, Math.PI * 2);
                    oc.fillStyle = color; oc.fill();
                    oc.strokeStyle = "#fff"; oc.lineWidth = 1.5; oc.stroke();
                }
                if (hasPurpleCoins && idx < purpleCoinsLen && purpleCoins[idx] !== null && purpleCoins[idx] !== undefined)
                    drawBead(purpleCoins[idx], "#ce93d8", yOfPurple);
                if (hasYellowCoins && idx < yellowCoinsLen && yellowCoins[idx] !== null && yellowCoins[idx] !== undefined)
                    drawBead(yellowCoins[idx], "#ffd54f", yOfCombined);

                if (hasVirtualAssetSeries) {
                    var minT_va = apTs[visibleStart];
                    var maxT_va = apTs[Math.max(0, visibleEnd - 1)];
                    var tr_va = maxT_va - minT_va || 1;
                    var closestIdx_va = -1, closestDist_va = 600000;
                    for (var j = 0; j < lineVirtualAssetTs.length; j++) {
                        if (lineVirtualAssetTs[j] < minT_va || lineVirtualAssetTs[j] > maxT_va) continue;
                        var xj = pad.l + ((lineVirtualAssetTs[j] - minT_va) / tr_va) * gW;
                        var dist = Math.abs(mx_ - xj);
                        if (dist < closestDist_va) { closestDist_va = dist; closestIdx_va = j; }
                    }
                    if (closestIdx_va !== -1 && closestDist_va < 600000)
                        drawBead(lineVirtualAsset[closestIdx_va], "#4fc3f7", yOfCombined);
                }
                if (hasAssetSeries) {
                    var minT_a = apTs[visibleStart];
                    var maxT_a = apTs[Math.max(0, visibleEnd - 1)];
                    var tr_a = maxT_a - minT_a || 1;
                    var closestIdx_a = -1, closestDist_a = 600000;
                    for (var j = 0; j < lineAssetTs.length; j++) {
                        if (lineAssetTs[j] < minT_a || lineAssetTs[j] > maxT_a) continue;
                        var xj = pad.l + ((lineAssetTs[j] - minT_a) / tr_a) * gW;
                        var dist = Math.abs(mx_ - xj);
                        if (dist < closestDist_a) { closestDist_a = dist; closestIdx_a = j; }
                    }
                    if (closestIdx_a !== -1 && closestDist_a < 600000)
                        drawBead(lineAsset[closestIdx_a], "#81c784", yOfCombined);
                }

                // 海里数 bead
                if (hasDistanceSeries && idx < lineDistance.length && lineDistance[idx] !== null && lineDistance[idx] !== undefined)
                    drawBead(lineDistance[idx], "#1565c0", yOfCombined);

                oc.setTransform(1, 0, 0, 1, 0, 0);

                var diff = idx > 0 ? (ap[idx] - ap[idx - 1]) : 0;
                var isUp = diff >= 0;
                var dc = isUp ? "#ef5350" : "#26a69a";
                var ds = (isUp ? "+" : "") + diff;
                var tooltipRows = [
                    { style: { color: "#888", marginBottom: "4px", fontWeight: "600" }, parts: [{ type: 'text', value: labels[idx] }] },
                    { parts: [{ type: 'text', value: "体力: " }, { type: 'bold', value: String(ap[idx]), style: { color: "#64b5f6" } }] },
                    { parts: [{ type: 'text', value: "单次变化: " }, { type: 'bold', value: ds, style: { color: dc } }] }
                ];

                if (isDetailMode) {
                    var source = sources && sources[idx] ? sources[idx] : '-';
                    var sourceColor = source === 'cl1' ? '#64b5f6' : (source === 'meow' ? '#ff9800' : '#888');
                    tooltipRows.push({ parts: [{ type: 'text', value: "来源: " }, { type: 'bold', value: source, style: { color: sourceColor } }] });
                }

                // 黄币 tooltip
                if (hasYellowCoins && idx < yellowCoinsLen && yellowCoins[idx] !== null && yellowCoins[idx] !== undefined) {
                    var yc = yellowCoins[idx];
                    var ycDiff = idx > 0 && yellowCoins[idx - 1] !== null && yellowCoins[idx - 1] !== undefined ? (yc - yellowCoins[idx - 1]) : 0;
                    var ycColor = ycDiff >= 0 ? "#ef5350" : "#26a69a";
                    var ycDiffStr = (ycDiff >= 0 ? "+" : "") + ycDiff;
                    tooltipRows.push({ parts: [{ type: 'text', value: "黄币: " }, { type: 'bold', value: String(yc), style: { color: "#ffd54f" } }, { type: 'text', value: " (" + ycDiffStr + ")", style: { color: ycColor } }] });
                }

                // 紫币 tooltip
                if (hasPurpleCoins && idx < purpleCoinsLen && purpleCoins[idx] !== null && purpleCoins[idx] !== undefined) {
                    var pc = purpleCoins[idx];
                    var pcDiff = idx > 0 && purpleCoins[idx - 1] !== null && purpleCoins[idx - 1] !== undefined ? (pc - purpleCoins[idx - 1]) : 0;
                    var pcColor = pcDiff >= 0 ? "#ef5350" : "#26a69a";
                    var pcDiffStr = (pcDiff >= 0 ? "+" : "") + pcDiff;
                    tooltipRows.push({ parts: [{ type: 'text', value: "紫币: " }, { type: 'bold', value: String(pc), style: { color: "#ce93d8" } }, { type: 'text', value: " (" + pcDiffStr + ")", style: { color: pcColor } }] });
                }

                // 虚拟资产 tooltip（时间戳匹配）
                if (hasVirtualAssetSeries) {
                    var ratio = (mx_ - pad.l) / gW;
                    var minT_va = apTs[visibleStart];
                    var maxT_va = apTs[Math.max(0, visibleEnd - 1)];
                    var targetTs = minT_va + ratio * (maxT_va - minT_va);
                    var closestIdx = -1, closestDist = Infinity;
                    for (var j = 0; j < lineVirtualAssetTs.length; j++) {
                        if (lineVirtualAssetTs[j] < minT_va || lineVirtualAssetTs[j] > maxT_va) continue;
                        var dist = Math.abs(lineVirtualAssetTs[j] - targetTs);
                        if (dist < closestDist) { closestDist = dist; closestIdx = j; }
                    }
                    if (closestIdx !== -1 && closestDist < 600000) {
                        tooltipRows.push({ parts: [{ type: 'text', value: "虚拟资产: " }, { type: 'bold', value: lineVirtualAsset[closestIdx].toFixed(1), style: { color: "#4fc3f7" } }] });
                    }
                }

                // 资产 tooltip（时间戳匹配）
                if (hasAssetSeries) {
                    var ratio = (mx_ - pad.l) / gW;
                    var minT_a = apTs[visibleStart];
                    var maxT_a = apTs[Math.max(0, visibleEnd - 1)];
                    var targetTs = minT_a + ratio * (maxT_a - minT_a);
                    var closestIdx = -1, closestDist = Infinity;
                    for (var j = 0; j < lineAssetTs.length; j++) {
                        if (lineAssetTs[j] < minT_a || lineAssetTs[j] > maxT_a) continue;
                        var dist = Math.abs(lineAssetTs[j] - targetTs);
                        if (dist < closestDist) { closestDist = dist; closestIdx = j; }
                    }
                    if (closestIdx !== -1 && closestDist < 600000) {
                        tooltipRows.push({ parts: [{ type: 'text', value: "资产: " }, { type: 'bold', value: lineAsset[closestIdx].toFixed(1), style: { color: "#81c784" } }] });
                    }
                }

                // 海里数 tooltip
                if (hasDistanceSeries && idx < lineDistance.length && lineDistance[idx] !== null && lineDistance[idx] !== undefined) {
                    var d = lineDistance[idx];
                    var dDiff = idx > 0 && lineDistance[idx - 1] !== null && lineDistance[idx - 1] !== undefined ? (d - lineDistance[idx - 1]) : 0;
                    var dColor = dDiff >= 0 ? "#ef5350" : "#26a69a";
                    var dDiffStr = (dDiff >= 0 ? "+" : "") + dDiff;
                    tooltipRows.push({ parts: [{ type: 'text', value: "海里数: " }, { type: 'bold', value: String(d), style: { color: "#1565c0" } }, { type: 'text', value: " (" + dDiffStr + ")", style: { color: dColor } }] });
                }

                setTooltipContent(tipEl, tooltipRows);
            } else {
                // K线图的鼠标交互（与上游一致）
                var idx = Math.floor((mx_ - pad.l) / candleSpace);
                idx = Math.max(0, Math.min(nn - 1, idx));
                var cx = xCenter(idx);

                oc.strokeStyle = "rgba(255,255,255,0.18)";
                oc.lineWidth = 1;
                oc.setLineDash([4, 3]);
                oc.beginPath(); oc.moveTo(cx, pad.t); oc.lineTo(cx, pad.t + gH); oc.stroke();
                oc.beginPath(); oc.moveTo(pad.l, my_); oc.lineTo(W - pad.r, my_); oc.stroke();
                oc.setLineDash([]);

                oc.strokeStyle = "#fff";
                oc.lineWidth = 1;
                oc.globalAlpha = 0.15;
                oc.fillStyle = "#fff";
                oc.fillRect(cx - candleW / 2 - 2, pad.t, candleW + 4, gH);
                oc.globalAlpha = 1.0;
                oc.setTransform(1, 0, 0, 1, 0, 0);

                var o = opens[idx], h = highs[idx], l = lows[idx], c_ = closes[idx];
                var chg = c_ - o;
                var chgPct = o !== 0 ? ((chg / o) * 100).toFixed(1) : "0.0";
                var isUp = c_ >= o;
                var dc = isUp ? "#ef5350" : "#26a69a";
                var chgSign = chg >= 0 ? "+" : "";

                var ma5Val = "-";
                if (idx >= 4) {
                    var sum5 = 0; for (var j = 0; j < 5; j++) sum5 += closes[idx - j];
                    ma5Val = (sum5 / 5).toFixed(1);
                }
                var ma10Val = "-";
                if (idx >= 9) {
                    var sum10 = 0; for (var j = 0; j < 10; j++) sum10 += closes[idx - j];
                    ma10Val = (sum10 / 10).toFixed(1);
                }

                setTooltipContent(tipEl, [
                    { style: { color: "#888", marginBottom: "4px", fontWeight: "600" }, parts: [{ type: 'text', value: labels[idx] }] },
                    {
                        parts: [
                            { type: 'text', value: "开盘: " },
                            { type: 'bold', value: String(o) },
                            { type: 'text', value: "  MA5(5期平均): " + ma5Val, style: { marginLeft: "8px", color: "#ffeb3b" } }
                        ]
                    },
                    {
                        parts: [
                            { type: 'text', value: "收盘: " },
                            { type: 'bold', value: String(c_), style: { color: dc } },
                            { type: 'text', value: "  MA10(10期平均): " + ma10Val, style: { marginLeft: "8px", color: "#e91e63" } }
                        ]
                    },
                    { parts: [{ type: 'text', value: "最高: " }, { type: 'bold', value: String(h), style: { color: "#ef5350" } }] },
                    { parts: [{ type: 'text', value: "最低: " }, { type: 'bold', value: String(l), style: { color: "#26a69a" } }] },
                    { parts: [{ type: 'text', value: "涨跌: " }, { type: 'bold', value: chgSign + chg + " (" + chgSign + chgPct + "%)", style: { color: dc } }] },
                    { style: { color: "#666", marginTop: "4px" }, parts: [{ type: 'text', value: "数据点密度: " + counts[idx] }] }
                ]);
            }

            tipEl.style.display = "block";
            var tx = (chartType === 'line' ? px : cx) + 18;
            var ty = my_ - 60;
            if (tx + 180 > W) tx = (chartType === 'line' ? px : cx) - 200;
            if (ty < 8) ty = my_ + 18;
            tipEl.style.left = tx + "px";
            tipEl.style.top = ty + "px";
        });

        cv.addEventListener("mouseleave", function () {
            tipEl.style.display = "none";
            oc.setTransform(1, 0, 0, 1, 0, 0);
            oc.clearRect(0, 0, ovCv.width, ovCv.height);
        });

        // ======== 缩放/平移（仅 line 图） ========
        if (chartType === 'line') {
            var zoomLevel = 1.0;
            var panOffset = 0;
            var maxZoom = 5.0;
            var minZoom = 0.5;

            function renderDetailChart() {
                var visibleStart = Math.max(0, Math.floor(panOffset));
                var visibleCount = Math.ceil(nn / zoomLevel);
                var visibleEnd = Math.min(nn, visibleStart + visibleCount);
                var visibleNn = visibleEnd - visibleStart;

                var dMin = 0, dMax = -Infinity;
                for (var i = visibleStart; i < visibleEnd; i++) {
                    if (ap[i] > dMax) dMax = ap[i];
                }
                if (dMax === -Infinity) dMax = 100;
                var drng = dMax - dMin || 1;
                dMax += drng * 0.1;

                ctx.fillStyle = "#1a1a2e";
                ctx.fillRect(0, 0, W, H);

                ctx.strokeStyle = "#2a2a3e";
                ctx.lineWidth = 1;
                ctx.fillStyle = "#666";
                ctx.font = "11px -apple-system, sans-serif";
                ctx.textAlign = "right";
                ctx.textBaseline = "middle";
                for (var i = 0; i <= 5; i++) {
                    var v = dMin + (dMax - dMin) * (i / 5);
                    var y = yScale(v, dMin, dMax);
                    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
                    ctx.fillText(Math.round(v), pad.l - 8, y);
                }

                var xScale = gW / Math.max(visibleNn - 1, 1);
                function dxOf(i) {
                    if (apTs && apTs.length === nn && visibleEnd > visibleStart) {
                        var minT = apTs[visibleStart];
                        var maxT = apTs[Math.max(0, visibleEnd - 1)];
                        var tr = maxT - minT || 1;
                        return pad.l + ((apTs[i] - minT) / tr) * gW;
                    }
                    return pad.l + (i - visibleStart) * xScale;
                }
                function dyOf(v) { return yScale(v, dMin, dMax); }

                drawAssetTicks(ctx, dyOf, dMin, dMax);

                // Ap 渐变填充
                var dgrad = ctx.createLinearGradient(0, pad.t, 0, pad.t + gH);
                dgrad.addColorStop(0, "rgba(100,181,246,0.15)");
                dgrad.addColorStop(1, "rgba(100,181,246,0.02)");
                ctx.beginPath();
                ctx.moveTo(dxOf(visibleStart), dyOf(ap[visibleStart]));
                for (var i = visibleStart + 1; i < visibleEnd; i++) {
                    ctx.lineTo(dxOf(i), dyOf(ap[i]));
                }
                ctx.lineTo(dxOf(visibleEnd - 1), pad.t + gH);
                ctx.lineTo(dxOf(visibleStart), pad.t + gH);
                ctx.closePath();
                ctx.fillStyle = dgrad;
                ctx.fill();

                // Ap 线
                ctx.lineWidth = 1.5;
                ctx.lineJoin = "round";
                for (var i = visibleStart + 1; i < visibleEnd; i++) {
                    ctx.beginPath();
                    ctx.moveTo(dxOf(i - 1), dyOf(ap[i - 1]));
                    ctx.strokeStyle = ap[i] >= ap[i - 1] ? "#ef5350" : "#26a69a";
                    ctx.lineTo(dxOf(i), dyOf(ap[i]));
                    ctx.stroke();
                }

                // Ap 数据点
                var dotInterval = Math.max(1, Math.floor(visibleNn / 50));
                for (var i = visibleStart; i < visibleEnd; i += dotInterval) {
                    ctx.beginPath();
                    ctx.arc(dxOf(i), dyOf(ap[i]), 2.5, 0, Math.PI * 2);
                    var dotColor = (i > visibleStart && ap[i] < ap[i - 1]) ? "#26a69a" : "#ef5350";
                    ctx.fillStyle = dotColor;
                    ctx.fill();
                }

                // 绘制额外系列线
                drawSeriesLine(dxOf, visibleStart, visibleEnd);

                // X 轴标签
                var labelInterval = Math.max(1, Math.floor(visibleNn / 8));
                for (var i = visibleStart; i < visibleEnd; i += labelInterval) {
                    var lx = dxOf(i);
                    ctx.save();
                    ctx.translate(lx, H - pad.b + 8);
                    ctx.rotate(0.3);
                    ctx.fillText(labels[i], 0, 0);
                    ctx.restore();
                }
            }

            renderDetailChart();

            var isDragging = false;
            var dragStartX = 0;
            var dragStartPan = 0;

            cv.addEventListener("mousedown", function (e) {
                isDragging = true;
                dragStartX = e.clientX;
                dragStartPan = panOffset;
                cv.style.cursor = "grabbing";
            });

            document.addEventListener("mousemove", function (e) {
                if (!isDragging) return;
                var dx = e.clientX - dragStartX;
                var visibleCount = Math.ceil(nn / zoomLevel);
                var xScale = gW / Math.max(visibleCount - 1, 1);
                var newPan = dragStartPan - dx / xScale;
                var maxPan = Math.max(0, nn - visibleCount);
                panOffset = Math.max(0, Math.min(maxPan, newPan));
                renderDetailChart();
            });

            document.addEventListener("mouseup", function () {
                if (isDragging) {
                    isDragging = false;
                    cv.style.cursor = "crosshair";
                }
            });

            cv.addEventListener("wheel", function (e) {
                e.preventDefault();
                var rect = cv.getBoundingClientRect();
                var mx = e.clientX - rect.left;
                var zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
                var newZoom = Math.max(minZoom, Math.min(maxZoom, zoomLevel * zoomFactor));
                if (newZoom !== zoomLevel) {
                    var visibleCountBefore = Math.ceil(nn / zoomLevel);
                    var visibleCountAfter = Math.ceil(nn / newZoom);
                    var xScaleBefore = gW / Math.max(visibleCountBefore - 1, 1);
                    var mouseIdx = panOffset + (mx - pad.l) / xScaleBefore;
                    zoomLevel = newZoom;
                    var xScaleAfter = gW / Math.max(visibleCountAfter - 1, 1);
                    panOffset = Math.max(0, mouseIdx - (mx - pad.l) / xScaleAfter);
                    var maxPan = Math.max(0, nn - visibleCountAfter);
                    panOffset = Math.max(0, Math.min(maxPan, panOffset));
                    renderDetailChart();
                }
            }, { passive: false });

            var zoomInBtn = document.getElementById(chartId + "_zoom_in");
            var zoomOutBtn = document.getElementById(chartId + "_zoom_out");
            var zoomResetBtn = document.getElementById(chartId + "_reset");

            if (zoomInBtn) {
                zoomInBtn.addEventListener("click", function () {
                    zoomLevel = Math.min(maxZoom, zoomLevel * 1.5);
                    var visibleCount = Math.ceil(nn / zoomLevel);
                    var maxPan = Math.max(0, nn - visibleCount);
                    panOffset = Math.min(panOffset, maxPan);
                    renderDetailChart();
                });
            }

            if (zoomOutBtn) {
                zoomOutBtn.addEventListener("click", function () {
                    zoomLevel = Math.max(minZoom, zoomLevel / 1.5);
                    renderDetailChart();
                });
            }

            if (zoomResetBtn) {
                zoomResetBtn.addEventListener("click", function () {
                    zoomLevel = 1.0;
                    panOffset = 0;
                    renderDetailChart();
                });
            }
        }
    }
})();
