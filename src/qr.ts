// A small QR code encoder for the pump.fun wallet page: the wallet's public
// address as a code the owner scans with his own wallet or exchange app to
// send SOL to it. Made here in the browser, so the address never goes to an
// outside QR service. Byte mode, versions 1 to 10, error correction L, M, Q or
// H, the standard masks and penalty rules (ISO/IEC 18004), after the
// structure of Project Nayuki's public-domain-style reference encoder. No
// dependencies; the tests compare it module by module with another encoder.

export type Ecc = "L" | "M" | "Q" | "H";

const ECC_FORMAT: Record<Ecc, number> = { L: 1, M: 0, Q: 3, H: 2 };
const ECC_INDEX: Record<Ecc, number> = { L: 0, M: 1, Q: 2, H: 3 };
export const MAX_VERSION = 10;

// Per version 1..10 (index 0 unused): error correction codewords per block, and blocks.
const ECC_PER_BLOCK = [
  [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18],
  [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26],
  [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24],
  [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28],
];
const BLOCKS = [
  [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4],
  [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5],
  [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8],
  [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8],
];

export interface QrCode {
  version: number;
  size: number;
  mask: number;
  ecc: Ecc;
  /** modules[y][x], true is dark. */
  modules: boolean[][];
}

function rawDataModules(ver: number): number {
  let r = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const n = Math.floor(ver / 7) + 2;
    r -= (25 * n - 10) * n - 55;
    if (ver >= 7) r -= 36;
  }
  return r;
}

function dataCodewords(ver: number, ecc: Ecc): number {
  const e = ECC_INDEX[ecc];
  return Math.floor(rawDataModules(ver) / 8) - ECC_PER_BLOCK[e][ver] * BLOCKS[e][ver];
}

function alignmentPositions(ver: number, size: number): number[] {
  if (ver === 1) return [];
  const n = Math.floor(ver / 7) + 2;
  const step = Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2;
  const out = [6];
  for (let p = size - 7; out.length < n; p -= step) out.splice(1, 0, p);
  return out;
}

// ── Reed-Solomon over GF(256), polynomial 0x11D ──

function gfMul(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

export function rsDivisor(degree: number): number[] {
  const r = new Array<number>(degree).fill(0);
  r[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < r.length; j++) {
      r[j] = gfMul(r[j], root);
      if (j + 1 < r.length) r[j] ^= r[j + 1];
    }
    root = gfMul(root, 0x02);
  }
  return r;
}

export function rsRemainder(data: number[], divisor: number[]): number[] {
  const r = divisor.map(() => 0);
  for (const b of data) {
    const factor = b ^ (r.shift() as number);
    r.push(0);
    divisor.forEach((coef, i) => (r[i] ^= gfMul(coef, factor)));
  }
  return r;
}

// ── the data bits ──

function dataBytes(bytes: Uint8Array, ver: number, ecc: Ecc): number[] | null {
  const capacity = dataCodewords(ver, ecc) * 8;
  const bits: number[] = [];
  const put = (v: number, n: number) => {
    for (let i = n - 1; i >= 0; i--) bits.push((v >>> i) & 1);
  };
  const countBits = ver < 10 ? 8 : 16;
  if (bytes.length >= 1 << countBits) return null;
  put(0b0100, 4);
  put(bytes.length, countBits);
  bytes.forEach((b) => put(b, 8));
  if (bits.length > capacity) return null;
  put(0, Math.min(4, capacity - bits.length));
  put(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) put(pad, 8);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) out.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  return out;
}

function withEcc(data: number[], ver: number, ecc: Ecc): number[] {
  const e = ECC_INDEX[ecc];
  const numBlocks = BLOCKS[e][ver];
  const eccLen = ECC_PER_BLOCK[e][ver];
  const raw = Math.floor(rawDataModules(ver) / 8);
  const numShort = numBlocks - (raw % numBlocks);
  const shortLen = Math.floor(raw / numBlocks);
  const div = rsDivisor(eccLen);
  const blocks: number[][] = [];
  for (let i = 0, k = 0; i < numBlocks; i++) {
    const dat = data.slice(k, k + shortLen - eccLen + (i < numShort ? 0 : 1));
    k += dat.length;
    const rem = rsRemainder(dat, div);
    if (i < numShort) dat.push(0);
    blocks.push(dat.concat(rem));
  }
  const out: number[] = [];
  for (let i = 0; i < blocks[0].length; i++) {
    blocks.forEach((b, j) => {
      if (i !== shortLen - eccLen || j >= numShort) out.push(b[i]);
    });
  }
  return out;
}

// ── the symbol ──

class Grid {
  readonly size: number;
  readonly m: boolean[][];
  readonly fn: boolean[][];

  constructor(readonly ver: number, readonly ecc: Ecc) {
    this.size = ver * 4 + 17;
    this.m = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
    this.fn = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false));
  }

  set(x: number, y: number, dark: boolean): void {
    this.m[y][x] = dark;
    this.fn[y][x] = true;
  }

  functionPatterns(): void {
    const s = this.size;
    for (let i = 0; i < s; i++) {
      this.set(6, i, i % 2 === 0);
      this.set(i, 6, i % 2 === 0);
    }
    this.finder(3, 3);
    this.finder(s - 4, 3);
    this.finder(3, s - 4);
    const pos = alignmentPositions(this.ver, s);
    const n = pos.length;
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        if (!((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0))) this.alignment(pos[i], pos[j]);
      }
    }
    this.formatBits(0);
    this.versionBits();
  }

  finder(x: number, y: number): void {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const d = Math.max(Math.abs(dx), Math.abs(dy));
        const xx = x + dx;
        const yy = y + dy;
        if (xx >= 0 && xx < this.size && yy >= 0 && yy < this.size) this.set(xx, yy, d !== 2 && d !== 4);
      }
    }
  }

  alignment(x: number, y: number): void {
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) this.set(x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }

  formatBits(mask: number): void {
    const data = (ECC_FORMAT[this.ecc] << 3) | mask;
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const bits = ((data << 10) | rem) ^ 0x5412;
    const bit = (i: number) => ((bits >>> i) & 1) !== 0;
    const s = this.size;
    for (let i = 0; i <= 5; i++) this.set(8, i, bit(i));
    this.set(8, 7, bit(6));
    this.set(8, 8, bit(7));
    this.set(7, 8, bit(8));
    for (let i = 9; i < 15; i++) this.set(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) this.set(s - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) this.set(8, s - 15 + i, bit(i));
    this.set(8, s - 8, true);
  }

  versionBits(): void {
    if (this.ver < 7) return;
    let rem = this.ver;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const bits = (this.ver << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >>> i) & 1) !== 0;
      const a = this.size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      this.set(a, b, dark);
      this.set(b, a, dark);
    }
  }

  codewords(data: number[]): void {
    let i = 0;
    const s = this.size;
    for (let right = s - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < s; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          const upward = ((right + 1) & 2) === 0;
          const y = upward ? s - 1 - vert : vert;
          if (!this.fn[y][x] && i < data.length * 8) {
            this.m[y][x] = ((data[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0;
            i++;
          }
        }
      }
    }
  }

  applyMask(mask: number): void {
    for (let y = 0; y < this.size; y++) {
      for (let x = 0; x < this.size; x++) {
        let inv: boolean;
        switch (mask) {
          case 0: inv = (x + y) % 2 === 0; break;
          case 1: inv = y % 2 === 0; break;
          case 2: inv = x % 3 === 0; break;
          case 3: inv = (x + y) % 3 === 0; break;
          case 4: inv = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break;
          case 5: inv = ((x * y) % 2) + ((x * y) % 3) === 0; break;
          case 6: inv = (((x * y) % 2) + ((x * y) % 3)) % 2 === 0; break;
          default: inv = (((x + y) % 2) + ((x * y) % 3)) % 2 === 0; break;
        }
        if (!this.fn[y][x] && inv) this.m[y][x] = !this.m[y][x];
      }
    }
  }

  penalty(): number {
    const s = this.size;
    let r = 0;
    const line = (get: (i: number) => boolean) => {
      let color = false;
      let run = 0;
      const hist = [0, 0, 0, 0, 0, 0, 0];
      for (let i = 0; i < s; i++) {
        if (get(i) === color) {
          run++;
          if (run === 5) r += 3;
          else if (run > 5) r++;
        } else {
          this.addHistory(run, hist);
          if (!color) r += this.finderLike(hist) * 40;
          color = get(i);
          run = 1;
        }
      }
      if (color) {
        this.addHistory(run, hist);
        run = 0;
      }
      run += s;
      this.addHistory(run, hist);
      r += this.finderLike(hist) * 40;
    };
    for (let y = 0; y < s; y++) line((x) => this.m[y][x]);
    for (let x = 0; x < s; x++) line((y) => this.m[y][x]);
    for (let y = 0; y < s - 1; y++) {
      for (let x = 0; x < s - 1; x++) {
        const c = this.m[y][x];
        if (c === this.m[y][x + 1] && c === this.m[y + 1][x] && c === this.m[y + 1][x + 1]) r += 3;
      }
    }
    let dark = 0;
    for (const row of this.m) for (const c of row) if (c) dark++;
    const total = s * s;
    r += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
    return r;
  }

  private addHistory(run: number, hist: number[]): void {
    if (hist[0] === 0) run += this.size; // the light border before the first run
    hist.pop();
    hist.unshift(run);
  }

  private finderLike(h: number[]): number {
    const n = h[1];
    const core = n > 0 && h[2] === n && h[3] === n * 3 && h[4] === n && h[5] === n;
    return (core && h[0] >= n * 4 && h[6] >= n ? 1 : 0) + (core && h[6] >= n * 4 && h[0] >= n ? 1 : 0);
  }
}

/**
 * Encode text (UTF-8, byte mode) at the smallest version that holds it.
 * `mask` -1 picks the mask with the lowest penalty; `version` forces one.
 */
export function encodeQr(text: string, ecc: Ecc = "M", opts: { mask?: number; version?: number } = {}): QrCode {
  const bytes = new TextEncoder().encode(text);
  let ver = opts.version ?? 1;
  let data: number[] | null = null;
  for (; ver <= MAX_VERSION; ver++) {
    data = dataBytes(bytes, ver, ecc);
    if (data || opts.version) break;
  }
  if (!data) throw new Error("The text is too long for a QR code here.");
  const g = new Grid(ver, ecc);
  g.functionPatterns();
  g.codewords(withEcc(data, ver, ecc));
  let mask = opts.mask ?? -1;
  if (mask < 0) {
    let best = Infinity;
    for (let i = 0; i < 8; i++) {
      g.applyMask(i);
      g.formatBits(i);
      const p = g.penalty();
      if (p < best) {
        best = p;
        mask = i;
      }
      g.applyMask(i);
    }
  }
  g.applyMask(mask);
  g.formatBits(mask);
  return { version: ver, size: g.size, mask, ecc, modules: g.m };
}

/** An SVG path (one unit per module, `quiet` modules of margin) of the dark modules. */
export function qrPath(code: QrCode, quiet = 4): string {
  const parts: string[] = [];
  code.modules.forEach((row, y) => {
    let x = 0;
    while (x < code.size) {
      if (!row[x]) {
        x++;
        continue;
      }
      let w = 1;
      while (x + w < code.size && row[x + w]) w++;
      parts.push(`M${x + quiet} ${y + quiet}h${w}v1h-${w}z`);
      x += w;
    }
  });
  return parts.join("");
}
