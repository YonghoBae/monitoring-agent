# Monitoring Agent

간단한 시스템 알림 데이터를 저장하고 자연어 유사도 검색을 제공하는 Spring Boot 기반 백엔드 서비스입니다. 알림을 저장하는 동시에 PGVector 기반 벡터스토어에 인덱싱하여, 이후 자연어 쿼리로 비슷한 알림을 빠르게 조회할 수 있습니다.

## 주요 기능
1. **알림 생성** (`POST /api/alerts`)
   - `level`(INFO/WARN/ERROR)과 `message`를 수신해서 `alert_event` 테이블에 저장합니다.
   - 저장 이후 즉시 `AlertVectorService`를 통해 PGVector에 인덱싱합니다.
   - 예외 흐름: DB 저장이나 벡터 인덱싱 실패 시 트랜잭션 전체를 롤백하고 호출자에게 예외를 전파합니다.
2. **미해결 알림 조회** (`GET /api/alerts/open`)
   - `resolved=false`인 최신 20건만 반환하여 현재 열려 있는 문제를 확인할 수 있도록 합니다.
   - 예외 흐름: 조회 중 DB 연결 실패 시 `500`으로 반환되며, 호출자 로그에 실패 원인을 남깁니다.
3. **유사 알림 검색** (`GET /api/alerts/similar`)
   - 자연어 `query`/`topK`를 받아 벡터 검색을 수행하고 `Document` 리스트를 그대로 반환합니다.
   - 예외 흐름: 벡터스토어 접속 실패나 결과 처리 중 문제 발생 시 `IOException`을 포함한 예외가 상위로 전파됩니다.

## 구성 요소
- `AlertEvent`: `level`, `message`, `createdAt`, `resolved` 필드를 가지는 JPA 엔티티.
- `AlertService`: Repository를 통해 알림을 저장하고 벡터 인덱싱을 트랜잭션 처리.
- `AlertVectorService`: `VectorStore`를 이용해 Document 형태로 인덱싱/검색.
- `AlertController`: REST API로 클라이언트 요청을 받아 DTO를 통해 입출력 처리.
- `AlertEventRepository`: `JpaRepository`로 기본 CRUD + 최근 미해결 알림 조회 커스텀 메서드 제공.

## 예외/정상 흐름 정리
| 기능 | 정상 시나리오 | 예외 시나리오 |
| --- | --- | --- |
| 알림 생성 | 입력을 저장하고 벡터 인덱싱 | 데이터베이스 권한 부족 or 벡터 인덱싱 실패 → 트랜잭션 전체 롤백 |
| 열린 알림 조회 | 최신 20건 반환 | DB 커넥션 실패 → HTTP 500 |
| 유사 알림 | `VectorStore.similaritySearch` 결과 반환 | Ollama/PGVector 미응답 → 예외 전파 |

## 개발/테스트
1. 데이터베이스 설정: `application.properties`에서 PostgreSQL 연결 정보를 맞춤.
2. 벡터 스토어/Ollama: `spring.ai.ollama` 설정을 로컬 실행 환경에 맞춰 조정.
3. 테스트 실행: `./gradlew test -Dspring.test.aot.enabled=false`

## 앞으로 개선할 점
- 입력 유효성 검증(`@Valid`, `@NotBlank`)을 컨트롤러에 추가하여 클라이언트 파라미터 오류를 처리.
- `AlertVectorService` 인덱싱 실패 시 리트라이 또는 비동기 워커 도입으로 안정성 확보.
- API 문서화(예: Spring REST Docs) 및 예외 응답 스펙을 README나 OpenAPI로 기술.
