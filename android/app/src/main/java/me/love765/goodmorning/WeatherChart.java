package me.love765.goodmorning;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;

import java.util.ArrayList;
import java.util.List;

/**
 * The website's hourly weather charts (briefing_document.weather_chart) as two white layers: the
 * accent layer (line, bars, values, sun and moon) and the muted layer (axis and period names). The
 * widget tints each, so the launcher can switch day and night colors without redrawing.
 */
final class WeatherChart {
    enum Kind { TEMPERATURE, RAIN, AIR }

    private final WeatherFrame frame;
    private final Kind kind;
    private final int past;
    private final float dp;
    private final String[] periods;

    WeatherChart(WeatherFrame frame, Kind kind, int past, float density, String[] periods) {
        this.frame = frame;
        this.kind = kind;
        this.past = past;
        this.dp = density;
        this.periods = periods;
    }

    /** Both layers at this size in pixels: [accent, muted]. Without period names the axis is the last row. */
    Bitmap[] draw(int width, int height) {
        Bitmap accent = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Bitmap muted = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas front = new Canvas(accent), back = new Canvas(muted);
        float row = 14 * dp, column = width / (float) WeatherFrame.HOURS;
        boolean bars = kind == Kind.RAIN;
        // Temperature and AQI put their values above the plot; rain puts them under its bars.
        int rows = periods == null ? 1 : 2;
        float top = bars ? 2 * dp : row + 2 * dp, bottom = height - rows * row - 8 * dp - (bars ? row : 0);
        float plot = bottom - top;
        int count = WeatherFrame.HOURS;

        Paint fill = paint(Paint.Style.FILL);
        for (double[] span : frame.night) {
            fill.setAlpha(20);
            front.drawRect((float) span[0] * column, top, (float) span[1] * column, bottom, fill);
        }
        int[] values = new int[count];
        for (int i = 0; i < count; i++) {
            values[i] = kind == Kind.TEMPERATURE ? (int) Math.round(frame.temp[i]) : kind == Kind.RAIN ? frame.rain[i] : frame.air[i];
        }
        List<Integer> labelled = new ArrayList<>();
        if (bars) {
            Paint grid = paint(Paint.Style.STROKE);
            grid.setStrokeWidth(dp);
            grid.setAlpha(90);
            grid.setPathEffect(new DashPathEffect(new float[] {3 * dp, 3 * dp}, 0));
            back.drawLine(0, top + plot / 2, width, top + plot / 2, grid);
            for (int i = 0; i < count; i++) {
                float h = Math.max(values[i], 2) / 100f * plot, x = i * column + column * .15f;
                fill.setAlpha(i < past ? 50 : values[i] >= WeatherFrame.WET ? 230 : 90);
                front.drawRoundRect(new RectF(x, bottom - h, x + column * .7f, bottom), 2 * dp, 2 * dp, fill);
            }
            // The wettest hours first, at least three hours apart, so labels never collide.
            Integer[] order = new Integer[count];
            for (int i = 0; i < count; i++) order[i] = i;
            java.util.Arrays.sort(order, (a, b) -> values[b] != values[a] ? values[b] - values[a] : a - b);
            for (int i : order) {
                boolean apart = true;
                for (int j : labelled) apart &= Math.abs(i - j) >= 3;
                if (values[i] >= 10 && apart) labelled.add(i);
            }
        } else {
            int high = Integer.MIN_VALUE, low = Integer.MAX_VALUE;
            for (int v : values) { high = Math.max(high, v); low = Math.min(low, v); }
            float span = Math.max(high - low, kind == Kind.TEMPERATURE ? 4 : 20);
            float[] ys = new float[count];
            Path line = new Path(), gone = new Path(), area = new Path();
            for (int i = 0; i < count; i++) {
                float x = (i + .5f) * column;
                ys[i] = top + plot * .12f + (high - values[i]) / span * plot * .76f;
                if (i == 0) { area.moveTo(x, bottom); }
                area.lineTo(x, ys[i]);
                if (i <= past) { if (i == 0) gone.moveTo(x, ys[i]); else gone.lineTo(x, ys[i]); }
                if (i >= past) { if (i == past) line.moveTo(x, ys[i]); else line.lineTo(x, ys[i]); }
            }
            area.lineTo((count - .5f) * column, bottom);
            area.close();
            fill.setAlpha(22);
            front.drawPath(area, fill);
            Paint stroke = paint(Paint.Style.STROKE);
            stroke.setStrokeWidth(2.2f * dp);
            stroke.setStrokeJoin(Paint.Join.ROUND);
            if (past > 0) {
                stroke.setAlpha(110);
                stroke.setPathEffect(new DashPathEffect(new float[] {3 * dp, 4 * dp}, 0));
                front.drawPath(gone, stroke);
            }
            stroke.setAlpha(255);
            stroke.setPathEffect(null);
            front.drawPath(line, stroke);
            for (int i = 0; i < count; i += 3) {
                fill.setAlpha(i < past ? 60 : 255);
                front.drawCircle((i + .5f) * column, ys[i], 3.2f * dp, fill);
                labelled.add(i);
            }
        }
        // Value labels: above the plot for lines, under the bars for rain.
        Paint value = text(11, true);
        float valueY = bars ? bottom + row - 2 * dp : row - 2 * dp;
        for (int i : labelled) {
            value.setAlpha(i < past ? 120 : 255);
            String label = values[i] + (kind == Kind.TEMPERATURE ? "°" : kind == Kind.RAIN ? "%" : "");
            front.drawText(label, centered(i, column, width, value, label), valueY, value);
        }
        // Axis: hours every three, replaced near sunrise and sunset by the sun or moon and its time.
        float axis = height - rows * row - 6 * dp;
        Paint rule = paint(Paint.Style.STROKE);
        rule.setStrokeWidth(dp);
        rule.setAlpha(90);
        back.drawLine(0, axis, width, axis, rule);
        Paint hour = text(10, false);
        float hourY = axis + row - 2 * dp;
        List<Integer> marks = new ArrayList<>();
        for (int s = 0; s < frame.sun.length; s++) {
            int at = Math.min((int) frame.sun[s], count - 1);
            marks.add(at);
            String time = frame.clock(frame.sun[s]);
            float icon = 5 * dp, x = (at + .5f) * column;
            float textWidth = hour.measureText(time), left = x - (icon * 2 + 3 * dp + textWidth) / 2;
            hour.setAlpha(at < past ? 120 : 255);
            back.drawText(time, left + icon * 2 + 3 * dp, hourY, hour);
            fill.setAlpha(255);
            if (frame.sunrise[s]) sun(front, left + icon, hourY - 4 * dp, icon);
            else moon(front, left + icon, hourY - 4 * dp, icon);
        }
        for (int i = 0; i < count; i += 3) {
            boolean near = false;
            for (int m : marks) near |= Math.abs(i - m) <= 2;
            if (near) continue;
            String label = String.format("%02d", (frame.start.getHour() + i) % 24);
            hour.setAlpha(i < past ? 120 : 255);
            back.drawText(label, centered(i, column, width, hour, label), hourY, hour);
        }
        if (periods == null) return new Bitmap[] {accent, muted};
        // Three equal periods, divided by short rules.
        Paint name = text(10, true);
        float nameY = height - 3 * dp, third = width / 3f;
        for (int p = 0; p < 3; p++) {
            back.drawText(periods[p], third * p + (third - name.measureText(periods[p])) / 2, nameY, name);
            if (p > 0) back.drawLine(third * p, nameY - 10 * dp, third * p, nameY + 1 * dp, rule);
        }
        return new Bitmap[] {accent, muted};
    }

    private float centered(int index, float column, int width, Paint paint, String label) {
        float w = paint.measureText(label);
        return Math.max(0, Math.min(width - w, (index + .5f) * column - w / 2));
    }

    private Paint paint(Paint.Style style) {
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(0xFFFFFFFF);
        paint.setStyle(style);
        paint.setStrokeCap(Paint.Cap.ROUND);
        return paint;
    }

    private Paint text(int sp, boolean bold) {
        Paint paint = paint(Paint.Style.FILL);
        paint.setTextSize(sp * dp);
        paint.setTypeface(bold ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        return paint;
    }

    private void sun(Canvas canvas, float x, float y, float r) {
        Paint stroke = paint(Paint.Style.STROKE);
        stroke.setStrokeWidth(1.2f * dp);
        canvas.drawCircle(x, y, r * .45f, stroke);
        for (int a = 0; a < 8; a++) {
            double t = a * Math.PI / 4;
            canvas.drawLine(x + (float) Math.cos(t) * r * .7f, y + (float) Math.sin(t) * r * .7f,
                    x + (float) Math.cos(t) * r, y + (float) Math.sin(t) * r, stroke);
        }
    }

    private void moon(Canvas canvas, float x, float y, float r) {
        Path crescent = new Path();
        crescent.addCircle(x, y, r * .85f, Path.Direction.CW);
        Path bite = new Path();
        bite.addCircle(x + r * .45f, y - r * .35f, r * .7f, Path.Direction.CW);
        crescent.op(bite, Path.Op.DIFFERENCE);
        canvas.drawPath(crescent, paint(Paint.Style.FILL));
    }
}
