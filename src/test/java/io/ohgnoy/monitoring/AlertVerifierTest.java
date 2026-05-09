package io.ohgnoy.monitoring;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.ohgnoy.monitoring.infrastructure.prometheus.AlertVerifier;
import io.ohgnoy.monitoring.infrastructure.prometheus.VerificationResult;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class AlertVerifierTest {

    private HttpServer server;
    private AlertVerifier verifier;

    @BeforeEach
    void setUp() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.start();
        String baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        verifier = new AlertVerifier(RestClient.builder(), baseUrl, new ObjectMapper());
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    @Test
    void sameAlertNameAndLabelsReturnsConfirmed() {
        respondWithAlerts("""
                {
                  "status": "success",
                  "data": {
                    "alerts": [
                      {
                        "labels": {
                          "alertname": "HostOutOfDiskSpace",
                          "instance": "node:9100",
                          "mountpoint": "/data",
                          "device": "/dev/sda1"
                        },
                        "value": "1",
                        "activeAt": "2026-05-09T10:00:00Z"
                      }
                    ]
                  }
                }
                """);

        VerificationResult result = verifier.verify(
                "HostOutOfDiskSpace",
                "{\"alertname\":\"HostOutOfDiskSpace\",\"instance\":\"node:9100\",\"mountpoint\":\"/data\",\"device\":\"/dev/sda1\"}");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.CONFIRMED);
        assertThat(result.currentValue()).isEqualTo("1");
    }

    @Test
    void differentMountpointReturnsStale() {
        respondWithAlerts("""
                {
                  "status": "success",
                  "data": {
                    "alerts": [
                      {
                        "labels": {
                          "alertname": "HostOutOfDiskSpace",
                          "instance": "node:9100",
                          "mountpoint": "/data",
                          "device": "/dev/sda1"
                        }
                      }
                    ]
                  }
                }
                """);

        VerificationResult result = verifier.verify(
                "HostOutOfDiskSpace",
                "{\"alertname\":\"HostOutOfDiskSpace\",\"instance\":\"node:9100\",\"mountpoint\":\"/\",\"device\":\"/dev/sda1\"}");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.STALE);
    }

    @Test
    void differentDeviceReturnsStale() {
        respondWithAlerts("""
                {
                  "status": "success",
                  "data": {
                    "alerts": [
                      {
                        "labels": {
                          "alertname": "HostOutOfInodes",
                          "instance": "node:9100",
                          "mountpoint": "/data",
                          "device": "/dev/sda1"
                        }
                      }
                    ]
                  }
                }
                """);

        VerificationResult result = verifier.verify(
                "HostOutOfInodes",
                "{\"alertname\":\"HostOutOfInodes\",\"instance\":\"node:9100\",\"mountpoint\":\"/data\",\"device\":\"/dev/sdb1\"}");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.STALE);
    }

    @Test
    void differentClientLabelsReturnStale() {
        respondWithAlerts("""
                {
                  "status": "success",
                  "data": {
                    "alerts": [
                      {
                        "labels": {
                          "alertname": "ApolloGameInputBacklog",
                          "client_name": "desk",
                          "client_type": "game"
                        }
                      }
                    ]
                  }
                }
                """);

        VerificationResult result = verifier.verify(
                "ApolloGameInputBacklog",
                "{\"alertname\":\"ApolloGameInputBacklog\",\"client_name\":\"tablet\",\"client_type\":\"game\"}");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.STALE);
    }

    @Test
    void emptyLabelsJsonReturnsUnknown() {
        respondWithAlerts("""
                {"status":"success","data":{"alerts":[]}}
                """);

        VerificationResult result = verifier.verify("HostOutOfDiskSpace", "");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.UNKNOWN);
    }

    @Test
    void invalidLabelsJsonReturnsUnknown() {
        respondWithAlerts("""
                {"status":"success","data":{"alerts":[]}}
                """);

        VerificationResult result = verifier.verify("HostOutOfDiskSpace", "{not-json");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.UNKNOWN);
    }

    @Test
    void prometheusFailureReturnsUnknown() {
        server.createContext("/api/v1/alerts", exchange -> {
            byte[] body = "error".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(500, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });

        VerificationResult result = verifier.verify("HostOutOfDiskSpace", "{\"alertname\":\"HostOutOfDiskSpace\"}");

        assertThat(result.status()).isEqualTo(VerificationResult.Status.UNKNOWN);
    }

    private void respondWithAlerts(String body) {
        server.createContext("/api/v1/alerts", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
    }
}
