import SwiftUI

/// Settings › Passwords: the switch for the Mac's Passwords app, and, once
/// on, the pairing — Connect…, the code your Mac shows typed in here, and
/// Disconnect. The code is typed into Search, never into a page.
struct ApplePasswordsCard: View {
    @ObservedObject var prefs: Preferences
    @ObservedObject private var apple = ApplePasswords.shared
    @State private var code = ""
    @FocusState private var typing: Bool

    var body: some View {
        Card {
            Line("Passwords from Apple's Passwords app",
                 "Accounts saved in the Passwords app, under the sign-in box. Unofficial: Search talks to the helper Apple made for its Chrome extension, as that extension. Never in private tabs.") {
                Switch(on: $prefs.applePasswords)
            }
            if prefs.applePasswords {
                Rule()
                pairing
            }
        }
        .onChange(of: apple.state) { _, state in
            code = ""
            if state == .code { typing = true }
        }
    }

    @ViewBuilder private var pairing: some View {
        switch apple.state {
        case .idle:
            Line(apple.trouble ?? "Not connected", "Your Mac shows a code, and you type it here. Once per launch of Search.") {
                Pill("Connect…") { Task { await apple.connect() } }
            }
        case .starting:
            Line("Connecting…", "Waiting for your Mac to show a code") { EmptyView() }
        case .code, .checking:
            Line("Enter the code your Mac shows", apple.state == .checking ? "Checking…" : "Six digits, from the Passwords window") {
                HStack(spacing: 8) {
                    TextField("000000", text: $code)
                        .textFieldStyle(.plain)
                        .font(.system(size: 13, design: .monospaced))
                        .frame(width: 70)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(Palette.wash, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
                        .focused($typing)
                        .onChange(of: code) { _, typed in
                            let digits = String(typed.filter(\.isNumber).prefix(6))
                            if digits != typed { code = digits }
                        }
                        .onSubmit(send)
                        .disabled(apple.state == .checking)
                    Pill("OK", filled: true, action: send)
                    Pill("Cancel") { apple.disconnect() }
                }
            }
        case .paired:
            Line("Connected", "Until Search quits. Accounts show under sign-in boxes, marked Apple Passwords; macOS may ask for Touch ID before one is filled.") {
                Pill("Disconnect") { apple.disconnect() }
            }
        }
    }

    private func send() {
        guard code.count == 6 else { return }
        let typed = code
        code = ""
        Task { await apple.enter(typed) }
    }
}
