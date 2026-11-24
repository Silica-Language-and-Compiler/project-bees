// The Erlang external term format, the subset tempus/1 uses: maps with atom keys, atoms, binaries, integers, lists.
// Written from development-plan/tempus-design.md section 5 and example_tempus_clients/writing-a-tempus-client.md.
// A usable example, to be used with care (README.md says what care means).

/// A body or a token this client does not accept. `reason` says why.
public struct Refused: Error, Equatable, CustomStringConvertible {
    public let reason: String
    public init(_ reason: String) { self.reason = reason }
    public var description: String { reason }
}

/// A fault of the caller: a value that has no tempus/1 form.
public struct Unencodable: Error, CustomStringConvertible {
    public let description: String
    public init(_ text: String) { description = text }
}

public typealias Bytes = [UInt8]

/// One term. A map's keys are atoms, held by name.
public indirect enum Term: Equatable, Sendable {
    case atom(String)
    case int(Int64)
    case binary(Bytes)
    case list([Term])
    case map([String: Term])

    public var atomName: String? { if case .atom(let s) = self { return s }; return nil }
    public var intValue: Int64? { if case .int(let n) = self { return n }; return nil }
    public var bytes: Bytes? { if case .binary(let b) = self { return b }; return nil }
    public var items: [Term]? { if case .list(let l) = self { return l }; return nil }
    public var fields: [String: Term]? { if case .map(let m) = self { return m }; return nil }
}

public let frameMax = 131072

package func be32(_ n: Int) -> Bytes {
    [UInt8((n >> 24) & 0xFF), UInt8((n >> 16) & 0xFF), UInt8((n >> 8) & 0xFF), UInt8(n & 0xFF)]
}

/// The order of map keys: the byte order of their names. It gives every frame exactly one byte form.
func keyOrder(_ a: String, _ b: String) -> Bool {
    Array(a.utf8).lexicographicallyPrecedes(Array(b.utf8))
}

private func encode(_ term: Term, into out: inout Bytes) throws {
    switch term {
    case .atom(let name):
        let raw = Array(name.utf8)
        guard raw.count <= 255 else { throw Unencodable("atom too long for tempus/1") }
        out.append(0x77)
        out.append(UInt8(raw.count))
        out += raw
    case .int(let n):
        if n >= 0 && n <= 255 {
            out += [0x61, UInt8(n)]
        } else if n >= -2147483648 && n <= 2147483647 {
            out.append(0x62)
            out += be32(Int(UInt32(bitPattern: Int32(n))))
        } else {
            var mag = n.magnitude
            var digits = Bytes()
            while mag > 0 {
                digits.append(UInt8(mag & 0xFF))
                mag >>= 8
            }
            out += [0x6e, UInt8(digits.count), n < 0 ? 1 : 0]
            out += digits
        }
    case .binary(let b):
        out.append(0x6d)
        out += be32(b.count)
        out += b
    case .list(let items):
        if !items.isEmpty {
            out.append(0x6c)
            out += be32(items.count)
            for x in items { try encode(x, into: &out) }
        }
        out.append(0x6a)
    case .map(let m):
        out.append(0x74)
        out += be32(m.count)
        for key in m.keys.sorted(by: keyOrder) {
            try encode(.atom(key), into: &out)
            try encode(m[key]!, into: &out)
        }
    }
}

/// The bytes of a term, beginning with the version byte 131.
public func etfEncode(_ term: Term) throws -> Bytes {
    var out: Bytes = [0x83]
    try encode(term, into: &out)
    return out
}

private struct Reader {
    let data: Bytes
    var pos: Int
    let depthMax: Int

    mutating func take(_ n: Int) throws -> ArraySlice<UInt8> {
        guard n >= 0, pos + n <= data.count else { throw Refused("truncated") }
        defer { pos += n }
        return data[pos..<(pos + n)]
    }

    mutating func byte() throws -> UInt8 { try take(1).first! }

    mutating func u32() throws -> Int {
        try take(4).reduce(0) { ($0 << 8) | Int($1) }
    }

    mutating func atom(_ n: Int) throws -> Term {
        let raw = try take(n)
        guard let name = String(validating: Array(raw), as: UTF8.self) else { throw Refused("bad_atom") }
        return .atom(name)
    }

    mutating func term(_ depth: Int) throws -> Term {
        guard depth <= depthMax else { throw Refused("too_deep") }
        let tag = try byte()
        switch tag {
        case 0x77:
            return try atom(Int(try byte()))
        case 0x76:
            let hi = Int(try byte()), lo = Int(try byte())
            return try atom((hi << 8) | lo)
        case 0x61:
            return .int(Int64(try byte()))
        case 0x62:
            return .int(Int64(Int32(bitPattern: UInt32(try u32()))))
        case 0x6e:
            let n = Int(try byte()), sign = try byte()
            guard n <= 8 else { throw Refused("unsupported") }
            var mag: UInt64 = 0
            for (i, b) in try take(n).enumerated() { mag |= UInt64(b) << UInt64(8 * i) }
            // this client keeps integers in 64 signed bits; every number of tempus/1 is far inside them
            if sign != 0 {
                guard mag <= UInt64(Int64.max) + 1 else { throw Refused("unsupported") }
                return .int(mag == UInt64(Int64.max) + 1 ? Int64.min : -Int64(mag))
            }
            guard mag <= UInt64(Int64.max) else { throw Refused("unsupported") }
            return .int(Int64(mag))
        case 0x6d:
            return .binary(Bytes(try take(try u32())))
        case 0x6a:
            return .list([])
        case 0x6c:
            let n = try u32()
            guard n <= data.count else { throw Refused("truncated") }
            var items: [Term] = []
            for _ in 0..<n { items.append(try term(depth + 1)) }
            guard try byte() == 0x6a else { throw Refused("bad_tag") }
            return .list(items)
        case 0x74:
            let n = try u32()
            guard n <= data.count else { throw Refused("truncated") }
            var m: [String: Term] = [:]
            for _ in 0..<n {
                guard case .atom(let key) = try term(depth + 1) else { throw Refused("bad_tag") }
                guard m[key] == nil else { throw Refused("duplicate_field") }
                m[key] = try term(depth + 1)
            }
            return .map(m)
        default:
            throw Refused([0x68, 0x69, 0x6b, 0x46].contains(tag) ? "bad_tag" : "unsupported")
        }
    }
}

/// One term from bytes that begin with the version byte 131 and hold nothing after the term.
public func etfDecode(_ data: Bytes, depthMax: Int = 6, sizeMax: Int = frameMax) throws -> Term {
    guard data.count <= sizeMax else { throw Refused("too_large") }
    guard data.count >= 1 else { throw Refused("truncated") }
    guard data[0] == 0x83 else { throw Refused("bad_version") }
    var r = Reader(data: data, pos: 1, depthMax: depthMax)
    let term = try r.term(1)
    guard r.pos == data.count else { throw Refused("trailing_bytes") }
    return term
}

public func hex(_ b: Bytes) -> String {
    let digits = Array("0123456789abcdef")
    var s = ""
    s.reserveCapacity(b.count * 2)
    for x in b {
        s.append(digits[Int(x >> 4)])
        s.append(digits[Int(x & 15)])
    }
    return s
}

public func unhex(_ s: String) -> Bytes? {
    let u = Array(s.utf8)
    guard u.count % 2 == 0 else { return nil }
    func v(_ c: UInt8) -> UInt8? {
        switch c {
        case 48...57: return c - 48
        case 97...102: return c - 87
        case 65...70: return c - 55
        default: return nil
        }
    }
    var out = Bytes()
    out.reserveCapacity(u.count / 2)
    var i = 0
    while i < u.count {
        guard let a = v(u[i]), let b = v(u[i + 1]) else { return nil }
        out.append(a << 4 | b)
        i += 2
    }
    return out
}
