// occt-import-js is built with Emscripten's embind, whose glue writes each binding's invoker as a string
// and compiles it with `new Function`. The Printers app's CSP forbids that ('unsafe-eval'), and loosening
// it on the page that holds printer tokens isn't worth a STEP picture. So the build swaps in the same
// invoker as a closure: what Emscripten itself emits with -sDYNAMIC_EXECUTION=0. Pinned to the package
// version: if the glue changes, noEval throws and the build stops rather than shipping a STEP reader
// that can't run.

const EVAL = 'var invokerFn=newFunc(Function,args)(...closureArgs);'

const CLOSURE = 'var invokerFn=function(...a){'
  + 'var destructors=needsDestructorStack?[]:null;var w=[cppTargetFunc];'
  + 'if(isClassMethodFunc){w.push(argTypes[1]["toWireType"](destructors,this))}'
  + 'for(var i=0;i<argCount-2;++i){w.push(argTypes[i+2]["toWireType"](destructors,a[i]))}'
  + 'var rv=cppInvokerFunc(...w);'
  + 'if(needsDestructorStack){runDestructors(destructors)}else{'
  + 'for(var i=isClassMethodFunc?1:2;i<argTypes.length;++i){'
  + 'if(argTypes[i].destructorFunction!==null){argTypes[i].destructorFunction(w[i===1?1:i-2+(isClassMethodFunc?2:1)])}}}'
  + 'if(returns){return argTypes[0]["fromWireType"](rv)}};'

export function noEval(code: string): string {
  if (!code.includes(EVAL)) throw new Error('occt-import-js: the embind invoker to replace was not found (package changed?)')
  return code.replace(EVAL, CLOSURE)
}
