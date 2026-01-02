use rafx_rs as rfx;

fn main() {
    rfx::open_window("Hello, World!", 1280, 720);

    while !rfx::window_should_close() {
        rfx::begin_frame();
        rfx::end_frame();
    }
}
