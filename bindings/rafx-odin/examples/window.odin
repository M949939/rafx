package window

import rfx "../"

main :: proc() {
    rfx.open_window("My Window", 800, 600)

    for !rfx.window_should_close() {
        rfx.begin_frame()
        rfx.end_frame()
    }
}
