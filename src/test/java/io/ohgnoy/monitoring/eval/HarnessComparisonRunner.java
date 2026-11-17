package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import io.ohgnoy.monitoring.application.agent.*;
import io.ohgnoy.monitoring.application.agent.tools.*;
import io.ohgnoy.monitoring.application.agent.evaluation.*;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.infrastructure.command.CommandExecutorService;
import io.ohgnoy.monitoring.infrastructure.discord.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.*;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.retry.support.RetryTemplate;
import java.net.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.io.IOException;
import static org.mockito.Mockito.*;

/** Explicit opt-in comparison. Same world/model/budget; raw answers precede any scoring. */
@Tag("eval")
@EnabledIfEnvironmentVariable(named="RUN_HARNESS_COMPARISON",matches="1")
class HarnessComparisonRunner {
    static final ObjectMapper JSON=new ObjectMapper();
    static String env(String key,String fallback){return System.getenv().getOrDefault(key,fallback);}
    static final String CORE=FocusedInvestigator.SYSTEM;
    @SuppressWarnings("unchecked") static <T> ObjectProvider<T> provider(T value){var p=mock(ObjectProvider.class);when(p.getIfAvailable()).thenReturn(value);return p;}
    @Test void compare() throws Exception {
        Path folder=Path.of("build/eval/comparison-"+System.currentTimeMillis());Files.createDirectories(folder);
        String source=Files.readString(Path.of(env("EVAL_DATASET","eval/v4/dataset.json")));JsonNode dataset=JSON.readTree(source);
        String model=env("EVAL_MODEL","qwen3.5:9b-pi32k"),url=env("EVAL_BASE_URL","http://127.0.0.1:11434");
        var client=ChatClient.builder(OpenAiChatModel.builder().openAiApi(OpenAiApi.builder().baseUrl(url).apiKey("ollama").build())
            .defaultOptions(OpenAiChatOptions.builder().model(model).temperature(0.0).maxTokens(1536).reasoningEffort("none").build())
            .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build()).build();
        Files.writeString(folder.resolve("dataset.json"),source);
        var conditions=JSON.valueToTree(Map.of("model",model,"endpoint",url,"arms",env("COMPARE_ARMS","production,pi"),"repeats",env("EVAL_REPEATS","1"),"piVersion","1.5.2","toolBudget",12,"timeoutSeconds",90,"maxTokens",1536,"temperature",0,"humanValidated",false));
        ((ObjectNode)conditions).put("primaryEvidence","Exact returned tool text; rawWorldTrace is diagnostic only")
            .put("deadlineScope","Compact investigation / Pi process launch through completion; runner configuration excluded; Pi CLI bootstrap included")
            .put("terminalPolicy","AgentExecution.call deadline and AgentExecution.finish partial results; Pi process killed on terminal stop")
            .put("armOrderPolicy","within-family-ordinal-plus-repeat-rotation-v1")
            .put("armOrderDefinition","Rotate configured arms left by (zero-based case ordinal within its family + zero-based repeat) modulo arm count; ordinals use full dataset order before filters")
            .put("maxTokensScope","Per completion, not total investigation tokens");
        Files.writeString(folder.resolve("conditions.json"),JSON.writeValueAsString(conditions));
        int repeats=Integer.parseInt(env("EVAL_REPEATS","1"));
        var caseOrdinals=familyOrdinals(dataset.path("scenarios"));
        for(JsonNode scene:dataset.path("scenarios")) {
            if(!env("EVAL_ONLY","").isBlank()&&!scene.path("id").asText().equals(env("EVAL_ONLY","")))continue;
            if(!env("EVAL_SPLIT","").isBlank()&&!scene.path("split").asText().equals(env("EVAL_SPLIT","")))continue;
            try(var world=new NumericEvalWorld(scene)) {
                for(int rep=0;rep<repeats;rep++) {
                    var arms=orderedArms(List.of(env("COMPARE_ARMS","production,pi").split(",")),
                        caseOrdinals.get(scene.path("id").asText()),rep);
                    for(String arm:arms) {
                        world.resetTrace();long start=System.nanoTime();String answer="",failure="";
                        var evidence=new DeliveredEvidence();
                        System.out.println("COMPARE_START "+scene.path("id").asText()+" "+arm+" "+rep);
                        try {
                            if(arm.equals("production"))answer=production(client,world,scene);
                            else if(arm.startsWith("pi"))answer=pi(folder,model,url,world,scene,arm.endsWith("_plus"),evidence);
                            else if(arm.startsWith("compact")) {
                                answer=new FocusedInvestigator(client,12,Duration.ofSeconds(90),Clock.fixed(world.evaluationTime,ZoneOffset.UTC)).investigate(prompt(scene,world),callbacks(world,arm.endsWith("_plus")),evidence::record).conclusion();
                            } else throw new IllegalArgumentException("Unknown arm "+arm);
                        }catch(Exception e){failure=e.toString();}
                        var row=JSON.createObjectNode().put("id",scene.path("id").asText()).put("family",scene.path("family").asText()).put("split",scene.path("split").asText()).put("arm",arm).put("rep",rep).put("answer",answer==null?"":answer).put("error",failure).put("elapsedMs",(System.nanoTime()-start)/1_000_000);
                        row.set("trace",evidence.trace(!arm.equals("production")));
                        row.set("rawWorldTrace",world.trace());
                        Files.writeString(folder.resolve("results.jsonl"),JSON.writeValueAsString(row)+"\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);
                        System.out.println("COMPARE_DONE "+scene.path("id").asText()+" "+arm+" error="+failure);
                    }
                }
            }
        }
        System.out.println("COMPARISON_COMPLETE "+folder.toAbsolutePath());
    }
    static Map<String,Integer> familyOrdinals(JsonNode scenes) {
        var familyCounts=new HashMap<String,Integer>();
        var ordinals=new LinkedHashMap<String,Integer>();
        for(var scene:scenes) {
            int ordinal=familyCounts.merge(scene.path("family").asText(),1,Integer::sum)-1;
            if(ordinals.put(scene.path("id").asText(),ordinal)!=null)throw new IllegalArgumentException("Duplicate case ID");
        }
        return Collections.unmodifiableMap(ordinals);
    }
    static List<String> orderedArms(List<String> configured,int familyOrdinal,int repeat) {
        if(configured.isEmpty()||familyOrdinal<0||repeat<0)throw new IllegalArgumentException("Invalid arm-order inputs");
        var arms=new ArrayList<>(configured);
        // For two arms this alternates by parity. Unlike nearby Random seeds,
        // the complete balanced grid is explicit and independently testable.
        Collections.rotate(arms,-Math.floorMod(familyOrdinal+repeat,arms.size()));
        return arms;
    }
    static String prompt(JsonNode s,NumericEvalWorld w){
        return s.path("question").asText()+"\n고정 관측 기준 시각: "+w.evaluationTime+". 실행 시각과 구분한다.\n"
            +(s.path("task_mode").asText().equals("alert")?"현재 알람 입력: "+s.path("alert"):"")
            +"\n답변에는 설명과 함께 다음 질문들의 결과를 마지막 JSON 코드블록으로 제출한다. 형식: {\"facts\":{\"key\":값},\"unknowns\":[\"미확인사항\"]}. 값을 모르면 null을 쓴다. key는 답변용 별칭이며 실제 메트릭 이름이 아니다. 실제 이름은 조회 도구로 확인한다.\n질문: "+s.path("answer_fields");
    }
    static String production(ChatClient client,NumericEvalWorld world,JsonNode s){
        var factory=world.toolsFactory();var web=mock(WebSearchTool.class);when(web.web_search(anyString())).thenReturn("평가 세계에는 외부 검색 자료가 없습니다.");
        if(s.path("task_mode").asText().equals("question")) {
            var executor=mock(CommandExecutorService.class);var pending=mock(PendingApprovalStore.class);
            var agent=new ConversationAgent(provider(client),factory,new ConversationToolsFactory(executor,pending),web);
            org.springframework.test.util.ReflectionTestUtils.setField(agent,"observationClock",Clock.fixed(world.evaluationTime,ZoneOffset.UTC));
            return agent.chat(new ConversationSession("eval-"+UUID.randomUUID(),null),prompt(s,world));
        }
        var judge=new AgentJudgeEvaluator(provider(null),mock(AgentEvaluationRepository.class),JSON,false,1);
        var agent=new ReActAgent(provider(client),provider(new ReflectionAdvisor(client)),factory,web,judge,"v4");
        org.springframework.test.util.ReflectionTestUtils.setField(agent,"observationClock",Clock.fixed(world.evaluationTime,ZoneOffset.UTC));
        var a=s.path("alert");var alert=new AlertEvent("WARNING",a.path("message").asText(),a.path("name").asText(),a.path("labels").toString(),null,null,world.evaluationTime.minusSeconds(600),null);
        return agent.runWithContext(alert,new ActionRecommendation("읽기 전용",ActionRecommendation.Category.READ_ONLY,null),prompt(s,world)).conclusion();
    }
    static ToolCallback[] callbacks(NumericEvalWorld world,boolean enhanced){
        var f=world.toolsFactory();return enhanced?ToolCallbacks.from(f.createAgentTools(),f.createDiscoveryTools()):ToolCallbacks.from(f.createAgentTools());
    }
    /** Primary evidence is the exact text exposed to the agent, never raw backend responses. */
    static final class DeliveredEvidence {
        private final ArrayNode observations=JSON.createArrayNode();
        synchronized void record(AgentExecution.ToolObservation observation) {
            observations.addObject().put("id","delivered-"+observations.size())
                .put("tool",observation.tool()).put("input",observation.input()).put("output",observation.output());
        }
        synchronized ObjectNode trace(boolean supported) {
            var trace=JSON.createObjectNode().put("kind","delivered_tool_results").put("captureSupported",supported);
            if(!supported)trace.put("limitation","Production arm has no exact delivery observer; rawWorldTrace must not substitute for reached evidence.");
            trace.set("observations",observations.deepCopy());
            return trace;
        }
    }

    /** Terminal stops close the exchange and kill Pi; they are never ordinary tool-error content. */
    static void deliverPiTool(HttpExchange exchange,Map<String,ToolCallback> tools,AgentExecution execution,
                              Runnable terminate,DeliveredEvidence evidence)throws IOException {
        try(exchange) {
            String out,name="unknown",input="";
            try {
                var request=JSON.readTree(exchange.getRequestBody());
                name=request.path("name").asText();input=request.path("args").toString();
                var callback=tools.get(name);
                if(callback==null)throw new IllegalArgumentException("Unknown tool");
                out=execution.wrap(callback).call(input);
            }catch(AgentExecution.Stopped stopped){terminate.run();return;}
            catch(Exception e){out="TOOL_ERROR: "+e.getMessage();}
            byte[] bytes=out.getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200,bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.getResponseBody().flush();
            evidence.record(new AgentExecution.ToolObservation(name,input,out));
        }
    }

    static void terminatePi(Process process) {
        if(process!=null&&process.isAlive()) {
            process.descendants().forEach(ProcessHandle::destroyForcibly);
            process.destroyForcibly();
        }
    }

    static String finishPiExecution(AgentExecution execution,Process process,Path output) {
        String answer=null;
        try {
            answer=execution.call(()->{
                try {
                    process.waitFor();
                    execution.ensureActive();
                    if(process.exitValue()!=0)throw new IllegalStateException("pi exited "+process.exitValue()+" see "+output+".stderr");
                    return readPiAnswer(output);
                }catch(InterruptedException e){Thread.currentThread().interrupt();throw new AgentExecution.Stopped("Pi wait interrupted");}
                catch(IOException e){throw new IllegalStateException("Cannot read Pi output",e);}
            });
        }catch(AgentExecution.Stopped stopped){/* Same partial-result policy as FocusedInvestigator. */}
        finally {terminatePi(process);}
        return execution.finish(answer);
    }

    static String readPiAnswer(Path output)throws IOException {
        String answer="";
        for(String line:Files.readAllLines(output)) {
            try {
                var event=JSON.readTree(line);
                if(event.path("type").asText().equals("message_end")&&event.path("message").path("role").asText().equals("assistant")) {
                    var text=new StringBuilder();
                    for(var content:event.path("message").path("content"))if(content.path("type").asText().equals("text"))text.append(content.path("text").asText());
                    if(!text.isEmpty())answer=text.toString();
                }
            }catch(Exception ignored){/* Non-message CLI output is not an answer. */}
        }
        return answer;
    }

    static String pi(Path folder,String model,String url,NumericEvalWorld world,JsonNode s,boolean enhanced,DeliveredEvidence evidence)throws Exception {
        var callbacks=callbacks(world,enhanced);var tools=new HashMap<String,ToolCallback>();var defs=JSON.createArrayNode();
        for(var cb:callbacks){var d=cb.getToolDefinition();tools.put(d.name(),cb);var item=defs.addObject().put("name",d.name()).put("description",d.description());item.set("parameters",JSON.readTree(d.inputSchema()));}
        var executionRef=new AtomicReference<AgentExecution>();
        var processRef=new AtomicReference<Process>();
        var terminal=new AtomicBoolean();
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/tools",x->{byte[] b=defs.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);x.sendResponseHeaders(200,b.length);x.getResponseBody().write(b);x.close();});
        server.createContext("/call",x->deliverPiTool(x,tools,executionRef.get(),()->{terminal.set(true);terminatePi(processRef.get());},evidence));
        server.start();Path config=Files.createTempDirectory("monitoring-pi-eval-");
        try {
            var m=JSON.createObjectNode();var p=m.putObject("providers").putObject("eval-local");p.put("baseUrl",url+"/v1").put("api","openai-completions").put("apiKey","ollama");
            var entry=p.putArray("models").addObject().put("id",model).put("contextWindow",32768).put("maxTokens",1536).put("reasoning",false);
            entry.putArray("input").add("text");entry.putObject("samplingParams").put("temperature",0).put("reasoning_effort","none");
            Files.writeString(config.resolve("models.json"),m.toString());Files.writeString(config.resolve("settings.json"),"{\"compaction\":{\"enabled\":false},\"retry\":{\"enabled\":false}}");
            Path output=folder.resolve(s.path("id").asText()+"-pi-"+UUID.randomUUID()+".jsonl");
            var builder=new ProcessBuilder("pi","--offline","--no-session","--no-builtin-tools","--no-extensions","--no-mcp","--no-skills","--no-prompt-templates","--no-context-files","--no-approve","-e",Path.of("scripts/pi_eval_extension.ts").toAbsolutePath().toString(),"--provider","eval-local","--model",model,"--thinking","off","--system-prompt",CORE,"--mode","json","-p",prompt(s,world));
            builder.environment().put("PI_CODING_AGENT_DIR",config.toString());builder.environment().put("EVAL_TOOL_BRIDGE","http://127.0.0.1:"+server.getAddress().getPort());builder.environment().put("PI_TELEMETRY","0");
            builder.redirectOutput(output.toFile());builder.redirectError(folder.resolve(output.getFileName()+".stderr").toFile());
            var execution=new AgentExecution(12,Duration.ofSeconds(90),Clock.systemUTC(),Clock.fixed(world.evaluationTime,ZoneOffset.UTC));
            executionRef.set(execution);
            var process=builder.start();processRef.set(process);process.getOutputStream().close();
            if(terminal.get())terminatePi(process);
            return finishPiExecution(execution,process,output);
        }finally{terminatePi(processRef.get());server.stop(0);try(var paths=Files.walk(config)){for(var path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}
