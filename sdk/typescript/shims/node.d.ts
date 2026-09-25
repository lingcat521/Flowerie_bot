/**
 * 最小 Node 宿主类型声明（Flowerie TypeScript SDK · 零依赖编译用）。
 *
 * 为什么需要：本 SDK **不依赖任何 npm 包**，也不要求你安装 `@types/node`。
 * 但 tsc 自身不带 Node 类型，于是在没有 `@types/node` 的环境里编译 SDK 时，
 * 把本文件一起传给 tsc 即可（examples/typescript-plugin/run.sh 会自动判断并处理）：
 *
 *     tsc plugin.ts flowerie_sdk.ts shims/node.d.ts --target es2022 --module commonjs
 *
 * 有 `@types/node` 的项目**不要**引入本文件——会和官方声明重复。
 * 这里只声明 SDK 实际用到的 API；SDK 新增用到别的 API 时请同步补上，
 * tests/test_plugin_sdk_contract.py::test_typescript_shim_covers_host_apis 会守住这条约束。
 */

interface FlowerieStdin {
  on(event: "end", listener: () => void): unknown;
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  setEncoding(encoding: string): unknown;
  resume(): unknown;
}

interface FlowerieWritable {
  write(chunk: string): boolean;
}

declare const process: {
  argv: string[];
  env: Record<string, string | undefined>;
  cwd(): string;
  exitCode?: number;
  stdin: FlowerieStdin;
  stdout: FlowerieWritable;
  stderr: FlowerieWritable;
  on(event: string, listener: (...args: unknown[]) => void): unknown;
};

declare const Buffer: {
  byteLength(input: string, encoding?: string): number;
  from(input: string, encoding?: string): { toString(encoding?: string): string };
};

declare module "node:fs" {
  export function existsSync(path: string): boolean;
  export function mkdirSync(path: string, options?: { recursive?: boolean }): string | undefined;
  export function readFileSync(path: string, encoding: string): string;
  export function writeFileSync(path: string, data: string, encoding?: string): void;
  export function readdirSync(path: string): string[];
  export function renameSync(oldPath: string, newPath: string): void;
  export function unlinkSync(path: string): void;
}

declare module "node:path" {
  export function join(...parts: string[]): string;
  export function resolve(...parts: string[]): string;
  export function dirname(p: string): string;
  export function basename(p: string, ext?: string): string;
  export function isAbsolute(p: string): boolean;
}

declare module "node:readline" {
  export interface FlowerieReadline {
    on(event: "line", listener: (line: string) => void): FlowerieReadline;
    on(event: string, listener: (...args: unknown[]) => void): FlowerieReadline;
    close(): void;
  }
  export function createInterface(options: {
    input: unknown;
    output?: unknown;
    terminal?: boolean;
  }): FlowerieReadline;
}
