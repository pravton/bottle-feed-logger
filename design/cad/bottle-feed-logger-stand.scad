// =============================================================================
// Bottle Feed Logger — load-cell stand (parametric starter)
//
// Two parts: BASE (fixed end of the load cell + electronics) and
// PLATFORM (free end of the load cell; the bottle sits here).
// The load cell is mounted CANTILEVER-style with an air gap so it can flex.
//
// HOW TO USE:
//   1. Measure your load cell and set the parameters below.
//   2. Set part = "base" or "platform" (or "preview" to see both).
//   3. Render (F6) and export each STL.
//
// This is a starting point — tweak to fit your exact cell and bottle.
// The critical requirement is the AIR GAP so the cell can bend.
// See hardware/assembly.md.
// =============================================================================

// ---------------- WHICH PART TO RENDER ----------------
part = "preview";   // "base", "platform", or "preview"

// ---------------- LOAD CELL DIMENSIONS (MEASURE YOURS) ----------------
cell_length       = 80;   // mm, length of the bar
cell_width        = 13;   // mm
cell_height       = 13;   // mm
cell_hole_spacing = 15;   // mm, distance between the two holes at EACH end
cell_hole_dia     = 3.4;  // mm, screw clearance (kit uses M3 -> 3.4; M4 ~4.5, M5 ~5.5)
cell_end_inset    = 6;    // mm, how far the hole centers sit from each end

// ---------------- STAND DIMENSIONS ----------------
platform_size = 90;   // mm, square top the bottle sits on
base_size     = 110;  // mm, square footprint of the base
wall          = 3;    // mm
base_floor    = 3;    // mm
boss_h        = 10;   // mm, height of the mounting bosses under each cell end
air_gap       = 4;    // mm, clearance under the free (platform) end so it can flex
lip_h         = 4;    // mm, raised lip around the platform to catch drips
lip_w         = 2.5;  // mm

// ---------------- DERIVED ----------------
$fn = 48;

// Mounting boss with a screw hole, centered, for one END of the cell
module cell_end_bosses(z) {
    for (x = [-cell_hole_spacing/2, cell_hole_spacing/2]) {
        translate([x, 0, z])
            difference() {
                cylinder(h = boss_h, d = cell_hole_dia + 6);
                translate([0,0,-1])
                    cylinder(h = boss_h + 2, d = cell_hole_dia);
            }
    }
}

// ---------------- BASE ----------------
// Holds the FIXED end of the load cell + a cavity for electronics.
module base() {
    fixed_end_x = -cell_length/2 + cell_end_inset;

    difference() {
        union() {
            // base plate
            translate([0,0,0])
                roundedBox(base_size, base_size, base_floor, 4);
            // bosses for the fixed end of the cell
            translate([fixed_end_x, 0, base_floor])
                cell_end_bosses(0);
            // low side walls forming a shallow electronics tray
            difference() {
                translate([0,0,0]) roundedBox(base_size, base_size, base_floor + 14, 4);
                translate([0,0,base_floor])
                    roundedBox(base_size - 2*wall, base_size - 2*wall, 20, 3);
            }
        }
        // wire/cable channel out one side
        translate([base_size/2 - wall - 1, 0, base_floor + 3])
            cube([wall + 4, 12, 10], center = true);
    }
}

// ---------------- PLATFORM ----------------
// Attaches to the FREE end of the load cell; the bottle sits on top.
module platform() {
    free_end_x = cell_length/2 - cell_end_inset;

    union() {
        // platform plate
        difference() {
            roundedBox(platform_size, platform_size, wall, 4);
            // (optional) nothing cut for now
        }
        // drip lip around the edge
        difference() {
            roundedBox(platform_size, platform_size, wall + lip_h, 4);
            translate([0,0,wall])
                roundedBox(platform_size - 2*lip_w, platform_size - 2*lip_w, lip_h + 1, 3);
        }
        // downward bosses that reach the free end of the cell
        translate([free_end_x, 0, -boss_h])
            cell_end_bosses(0);
        // connecting rib from platform down to the bosses
        translate([free_end_x, 0, -boss_h/2])
            cube([cell_hole_spacing + 8, cell_width + 6, boss_h], center = true);
    }
}

// rounded box helper
module roundedBox(x, y, z, r) {
    hull() {
        for (sx = [-1,1], sy = [-1,1])
            translate([sx*(x/2 - r), sy*(y/2 - r), 0])
                cylinder(h = z, r = r);
    }
}

// ---------------- ASSEMBLY / PREVIEW ----------------
module preview() {
    color("LightSteelBlue") base();
    // platform floated above with the air gap, as it would sit in use
    translate([0,0, base_floor + boss_h + cell_height + air_gap])
        color("Khaki") platform();
    // representation of the load cell (not printed)
    color("Silver")
        translate([0,0, base_floor + boss_h + cell_height/2])
            cube([cell_length, cell_width, cell_height], center = true);
}

if (part == "base")          base();
else if (part == "platform") platform();
else                         preview();

// =============================================================================
// NOTES
// - The cantilever: fixed end bolts to the BASE bosses, free end bolts to the
//   PLATFORM bosses. The air_gap keeps the platform from touching the base so
//   the bar can flex. If anything binds, increase air_gap.
// - Verify hole spacing/diameter against YOUR cell before printing.
// - Print base bottom-down and platform top-down for clean surfaces.
// - Add a silicone coaster on the platform for a wipeable, food-friendly top.
// =============================================================================
