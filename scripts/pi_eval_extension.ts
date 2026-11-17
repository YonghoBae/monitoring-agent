// Explicitly loaded into an isolated pi CLI. No shell/file/MCP tools are enabled.
export default async function(pi: any) {
  const base=process.env.EVAL_TOOL_BRIDGE!;
  const definitions=await (await fetch(base+'/tools')).json() as any[];
  for(const def of definitions) pi.registerTool({
    name:def.name,label:def.name,description:def.description,parameters:def.parameters,
    async execute(_id:string,args:any) {
      const response=await fetch(base+'/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:def.name,args})});
      return {content:[{type:'text',text:await response.text()}],details:{}};
    }
  });
}
