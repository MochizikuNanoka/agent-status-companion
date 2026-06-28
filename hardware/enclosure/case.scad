// AI Agent Status Companion — 3D 外壳模型
// 适用于 ESP32 DevKit + SSD1306 128x64 + WS2812B
// 用 OpenSCAD 打开并导出 STL 打印
// 参数单位: mm

// ============ 可调参数 ============
wall = 2.0;           // 壁厚
tolerance = 0.4;      // 容差
box_w = 70;           // 外壳宽
box_d = 45;           // 外壳深
box_h = 25;           // 外壳高

// OLED 窗口 (正面)
oled_w = 30;          // SSD1306 可视区宽
oled_h = 14;          // SSD1306 可视区高
oled_x = (box_w - oled_w) / 2;  // 居中
oled_y = 8;           // 距顶部距离

// LED 孔 (正面)
led_d = 5;            // LED 开孔直径
led_x = box_w / 2;    // 居中
led_y = oled_y + oled_h + 6;

// USB 孔 (侧面)
usb_w = 10;
usb_h = 5;
usb_z = 4;            // 距底部高度

// 通风孔
vent_r = 2;
vent_spacing = 10;

// ============ 主体 ============
difference() {
    // 外壳本体
    cube([box_w, box_d, box_h]);
    
    // 内部挖空
    translate([wall, wall, wall])
        cube([box_w - 2*wall, box_d - 2*wall, box_h - wall + 1]);
    
    // OLED 窗口
    translate([oled_x, -1, oled_y])
        cube([oled_w, wall + 2, oled_h]);
    
    // LED 孔
    translate([led_x, -1, led_y])
        rotate([-90, 0, 0])
            cylinder(d=led_d, h=wall + 2, $fn=32);
    
    // USB 孔 (右侧面)
    translate([box_w + 1, box_d/2 - usb_w/2, usb_z])
        cube([wall + 2, usb_w, usb_h]);
    
    // 通风孔 (背面)
    for (i = [0:2]) {
        for (j = [0:1]) {
            translate([vent_spacing + i*vent_spacing*2,
                       box_d - wall - 1,
                       vent_spacing + j*vent_spacing*2])
                rotate([90, 0, 0])
                    cylinder(r=vent_r, h=wall + 2, $fn=16);
        }
    }
    
    // 底部通风孔
    for (i = [0:3]) {
        for (j = [0:2]) {
            translate([vent_spacing + i*vent_spacing*1.5,
                       vent_spacing + j*vent_spacing*1.5,
                       -1])
                cylinder(r=vent_r, h=wall + 2, $fn=16);
        }
    }
}

// ============ 盖板 (可选分离打印) ============
// 取消注释以下代码打印独立盖板
/*
translate([0, box_d + 10, 0]) {
    difference() {
        cube([box_w, box_d, wall]);
        
        // OLED 窗口
        translate([oled_x, wall - 1, 0])
            cube([oled_w, wall + 2, oled_h]);
        
        // LED 孔
        translate([led_x, wall - 1, led_y - wall])
            rotate([-90, 0, 0])
                cylinder(d=led_d, h=wall + 2, $fn=32);
        
        // 螺丝孔 (4 角)
        for (x = [5, box_w - 5]) {
            for (y = [5, box_d - 5]) {
                translate([x, y, -1])
                    cylinder(d=2.5, h=wall + 2, $fn=16);
            }
        }
    }
}
*/

echo("=== 打印参数 ===");
echo(str("外壳尺寸: ", box_w, " x ", box_d, " x ", box_h, " mm"));
echo(str("壁厚: ", wall, " mm"));
echo(str("材料用量估计: ~",
    (box_w*box_d*box_h - (box_w-2*wall)*(box_d-2*wall)*(box_h-wall)) / 1000,
    " cm³"));
echo("建议: PLA, 0.2mm 层高, 15% 填充, 无需支撑");
