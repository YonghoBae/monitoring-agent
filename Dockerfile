FROM eclipse-temurin:17-jdk-alpine AS builder
WORKDIR /app

# Copy Gradle wrapper & build files first to leverage layer caching
COPY gradlew gradlew
COPY gradle gradle
COPY build.gradle settings.gradle ./
RUN chmod +x gradlew

# Copy sources and build the executable jar
COPY src src
RUN ./gradlew bootJar -x test

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app

# Copy the built jar from the builder image
COPY --from=builder /app/build/libs/*.jar app.jar

EXPOSE 8080

# Allow JVM opts override while keeping default command simple
ENV JAVA_OPTS=""
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
