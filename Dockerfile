FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app

# Copy Gradle wrapper & build files first to leverage layer caching
COPY gradlew gradlew
COPY gradle gradle
COPY build.gradle settings.gradle ./
RUN chmod +x gradlew

# Copy sources and build the executable jar
# --mount=type=cache: Gradle 캐시를 빌드 간 재사용해 의존성 재다운로드 방지
COPY src src
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew bootJar -x test --build-cache

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

# docker.io(데몬 포함) 대신 CLI만 설치
RUN apk add --no-cache docker-cli

# Copy the built jar from the builder image
COPY --from=builder /app/build/libs/*.jar app.jar

EXPOSE 8080

# Allow JVM opts override while keeping default command simple
ENV JAVA_OPTS=""
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
