declare module 'occt-import-js' {
  const occtimportjs: (opts?: { locateFile?: (path: string) => string }) => Promise<import('./step').Occt>
  export default occtimportjs
}
