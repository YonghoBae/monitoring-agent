package io.ohgnoy.monitoring.eval;

import com.fasterxml.jackson.databind.JsonNode;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.application.agent.AgentExecution;
import io.ohgnoy.monitoring.application.agent.FocusedInvestigator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;
import org.springframework.retry.support.RetryTemplate;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;

import static io.ohgnoy.monitoring.eval.HarnessComparisonRunner.JSON;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Local fake endpoints only: no model provider, Pi installation or external fixture required. */
@Timeout(15)
class HarnessComparisonContractTest {
    @TempDir Path directory;
    private static final Clock OBSERVATION_CLOCK=Clock.fixed(Instant.parse("2026-11-17T00:00:00Z"),ZoneOffset.UTC);

    private ToolCallback tool(String result) {
        var callback=mock(ToolCallback.class);
        when(callback.getToolDefinition()).thenReturn(ToolDefinition.builder().name("read_status")
            .description("Read a bounded summary").inputSchema("{\"type\":\"object\",\"properties\":{}}").build());
        when(callback.getToolMetadata()).thenReturn(ToolMetadata.builder().build());
        when(callback.call(anyString(),any())).thenReturn(result);
        return callback;
    }

    @Test void compactEvidenceExactlyMatchesMessagesAndIncludesCacheDeliveries()throws Exception {
        var seen=new CopyOnWriteArrayList<JsonNode>();
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/v1/chat/completions",exchange->{
            try(exchange) {
                seen.add(JSON.readTree(exchange.getRequestBody()));
                int turn=seen.size();
                var message=JSON.createObjectNode().put("role","assistant");
                if(turn<=2) {
                    message.put("content","");
                    message.putArray("tool_calls").addObject().put("id","call-"+turn).put("type","function")
                        .putObject("function").put("name","read_status").put("arguments","{}");
                }else message.put("content","The recorded peak was observed.");
                byte[] response=JSON.writeValueAsBytes(Map.of("id","fake-"+turn,"object","chat.completion","model","fake",
                    "choices",List.of(Map.of("index",0,"finish_reason",turn<=2?"tool_calls":"stop","message",message))));
                exchange.getResponseHeaders().add("Content-Type","application/json");
                exchange.sendResponseHeaders(200,response.length);exchange.getResponseBody().write(response);
            }
        });
        server.start();
        try {
            var model=OpenAiChatModel.builder().openAiApi(OpenAiApi.builder().apiKey("local-test")
                .baseUrl("http://127.0.0.1:"+server.getAddress().getPort()).build())
                .retryTemplate(RetryTemplate.builder().maxAttempts(1).build()).build();
            var evidence=new HarnessComparisonRunner.DeliveredEvidence();
            String summary="Retained series only; observed peak=97; last=12; omitted series not exposed.";
            var callback=tool(JSON.writeValueAsString(summary));
            var result=new FocusedInvestigator(ChatClient.builder(model).build(),3,Duration.ofSeconds(10),OBSERVATION_CLOCK)
                .investigate("Read status",new ToolCallback[]{callback},evidence::record);
            assertThat(result.conclusion()).isEqualTo("The recorded peak was observed.");
            assertThat(seen).hasSize(3);
            var observed=evidence.trace(true).path("observations");
            assertThat(observed.size()).isEqualTo(2);
            var toolMessages=Stream.of(seen.get(2).path("messages")).flatMap(messages->{
                var list=new java.util.ArrayList<JsonNode>();messages.forEach(list::add);return list.stream();
            }).filter(message->message.path("role").asText().equals("tool")).toList();
            assertThat(toolMessages).hasSize(2);
            for(int i=0;i<2;i++) {
                String delivered=toolMessages.get(i).path("content").asText();
                assertThat(observed.get(i).path("output").asText()).isEqualTo(delivered);
                assertThat(observed.get(i).path("input").asText()).isEqualTo("{}");
                assertThat(JSON.readTree(delivered).path("data").asText()).isEqualTo(summary);
                assertThat(JSON.readTree(delivered).path("observed_at").asText()).isEqualTo(OBSERVATION_CLOCK.instant().toString());
            }
            assertThat(observed.get(0).path("id")).isNotEqualTo(observed.get(1).path("id"));
            verify(callback,times(1)).call(eq("{}"),any());
        }finally {server.stop(0);}
    }

    @Test void piBridgeRecordsExactHttpTextAndStopsWithoutToolErrorOnExhaustion()throws Exception {
        var execution=new AgentExecution(2,Duration.ofSeconds(10),Clock.systemUTC(),OBSERVATION_CLOCK);
        var callback=tool(JSON.writeValueAsString("query summary includes the actual peak"));
        var evidence=new HarnessComparisonRunner.DeliveredEvidence();
        var terminated=new AtomicBoolean();
        var delivered=new Semaphore(0);
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/call",exchange->{
            try {HarnessComparisonRunner.deliverPiTool(exchange,Map.of("read_status",callback),
                execution,()->terminated.set(true),evidence);}
            finally {delivered.release();}
        });
        server.start();
        try(var client=HttpClient.newHttpClient()) {
            var request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+server.getAddress().getPort()+"/call"))
                .timeout(Duration.ofSeconds(3)).POST(HttpRequest.BodyPublishers.ofString("{\"name\":\"read_status\",\"args\":{}}")).build();
            for(int i=0;i<2;i++) {
                String received=client.send(request,HttpResponse.BodyHandlers.ofString()).body();
                // Receipt of all HTTP bytes can precede the handler's evidence write.
                delivered.acquire();
                assertThat(evidence.trace(true).path("observations").get(i).path("output").asText()).isEqualTo(received);
                assertThat(JSON.readTree(received).path("data").asText()).isEqualTo("query summary includes the actual peak");
            }
            assertThatThrownBy(()->client.send(request,HttpResponse.BodyHandlers.ofString())).isInstanceOf(IOException.class);
            assertThat(terminated).isTrue();
            assertThat(evidence.trace(true).path("observations").size()).isEqualTo(2);
            verify(callback,times(1)).call("{}",null);
            String expected=execution.finish(null);
            assertThat(expected).contains("호출 한도","actual peak").doesNotContain("TOOL_ERROR");
            Path output=answerFile("This final answer must be discarded after terminal exhaustion.");
            assertThat(HarnessComparisonRunner.finishPiExecution(execution,completedProcess(),output)).isEqualTo(expected);
        }finally {server.stop(0);}
    }

    @Test void piDeadlineKillsWaitingProcessAndRetainsSamePartialObservations()throws Exception {
        var execution=new AgentExecution(12,Duration.ofMillis(300),Clock.systemUTC(),OBSERVATION_CLOCK);
        execution.wrap(tool("captured state before timeout")).call("{}");
        var alive=new AtomicBoolean(true);
        var killed=new AtomicInteger();
        var process=mock(Process.class);
        when(process.waitFor()).thenAnswer(invocation->{new CountDownLatch(1).await();return 0;});
        when(process.isAlive()).thenAnswer(invocation->alive.get());
        when(process.descendants()).thenAnswer(invocation->Stream.empty());
        when(process.destroyForcibly()).thenAnswer(invocation->{alive.set(false);killed.incrementAndGet();return process;});
        String result=HarnessComparisonRunner.finishPiExecution(execution,process,answerFile("An obsolete final answer"));
        assertThat(killed).hasValue(1);
        assertThat(alive).isFalse();
        assertThat(result).isEqualTo(execution.finish(null)).contains("시간 한도","captured state before timeout")
            .doesNotContain("obsolete final answer");
    }

    @Test void piUsesSharedFinishForUnavailableToolsAndPreservesOrdinaryFinalAnswers()throws Exception {
        var unavailable=new AgentExecution(12,Duration.ofSeconds(10));
        var broken=tool("unused");
        when(broken.call(anyString(),any())).thenThrow(new IllegalStateException("offline"));
        unavailable.wrap(broken).call("{}");
        Path answer=answerFile("Everything is healthy.");
        assertThat(HarnessComparisonRunner.finishPiExecution(unavailable,completedProcess(),answer))
            .isEqualTo(unavailable.finish("Everything is healthy.")).contains("확인 불가").doesNotContain("Everything is healthy.");
        var healthy=new AgentExecution(12,Duration.ofSeconds(10));
        assertThat(HarnessComparisonRunner.finishPiExecution(healthy,completedProcess(),answer)).isEqualTo("Everything is healthy.");
    }

    @Test void unsupportedProductionCaptureIsExplicitAndRawDataIsNotInvented() {
        var trace=new HarnessComparisonRunner.DeliveredEvidence().trace(false);
        assertThat(trace.path("captureSupported").asBoolean()).isFalse();
        assertThat(trace.path("observations").isEmpty()).isTrue();
        assertThat(trace.path("limitation").asText()).contains("rawWorldTrace must not substitute");
    }

    @Test void v5PlannedOrdersBalanceOverallWithinFamiliesAndWithinRepeats()throws Exception {
        var scenes=JSON.readTree(Files.readString(Path.of("eval/v5/dataset.json"))).path("scenarios");
        assertThat(scenes.size()).isEqualTo(8);
        var ordinals=HarnessComparisonRunner.familyOrdinals(scenes);
        var configured=List.of("compact_plus","pi_plus");
        var overall=new java.util.HashMap<String,Integer>();
        var byFamily=new java.util.HashMap<String,java.util.Map<String,Integer>>();
        var byRepeat=new java.util.HashMap<Integer,java.util.Map<String,Integer>>();
        for(var scene:scenes) {
            var perCase=new java.util.HashMap<String,Integer>();
            for(int repeat=0;repeat<3;repeat++) {
                var arms=HarnessComparisonRunner.orderedArms(configured,ordinals.get(scene.path("id").asText()),repeat);
                assertThat(arms).containsExactlyInAnyOrderElementsOf(configured);
                String first=arms.getFirst();
                overall.merge(first,1,Integer::sum);
                perCase.merge(first,1,Integer::sum);
                byFamily.computeIfAbsent(scene.path("family").asText(),key->new java.util.HashMap<>()).merge(first,1,Integer::sum);
                byRepeat.computeIfAbsent(repeat,key->new java.util.HashMap<>()).merge(first,1,Integer::sum);
            }
            assertThat(perCase.values()).containsExactlyInAnyOrder(1,2);
        }
        assertThat(overall).containsExactlyInAnyOrderEntriesOf(Map.of("compact_plus",12,"pi_plus",12));
        assertThat(byFamily).hasSize(2);
        byFamily.values().forEach(counts->assertThat(counts).containsExactlyInAnyOrderEntriesOf(Map.of("compact_plus",6,"pi_plus",6)));
        assertThat(byRepeat).hasSize(3);
        byRepeat.values().forEach(counts->assertThat(counts).containsExactlyInAnyOrderEntriesOf(Map.of("compact_plus",4,"pi_plus",4)));
        assertThat(configured).containsExactly("compact_plus","pi_plus");
        System.out.println("V5_ARM_ORDER overall="+overall+" families="+byFamily+" repeats="+byRepeat+" model_calls=0");
    }

    private Process completedProcess()throws InterruptedException {
        var process=mock(Process.class);
        when(process.waitFor()).thenReturn(0);
        when(process.exitValue()).thenReturn(0);
        when(process.isAlive()).thenReturn(false);
        return process;
    }

    private Path answerFile(String text)throws IOException {
        Path output=Files.createTempFile(directory,"pi-",".jsonl");
        Files.writeString(output,JSON.writeValueAsString(Map.of("type","message_end","message",Map.of("role","assistant",
            "content",List.of(Map.of("type","text","text",text)))))+"\n");
        return output;
    }
}
