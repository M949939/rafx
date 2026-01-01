#include "HandmadeMath.h"
#include "rafx.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

const char* shaderSource = R"(
#include "rafx.slang"

struct VertexInput {
    float3 pos      : POSITION;
    float3 normal   : NORMAL;
};

struct ShadowUniforms {
    float4x4 lightMVP;
};
RFX_PUSH_CONSTANTS(ShadowUniforms, u_Shadow);

struct ShadowOutput {
    float4 pos : SV_Position;
};

[shader("vertex")]
ShadowOutput vsShadow(VertexInput input) {
    ShadowOutput output;
    output.pos = mul(u_Shadow.lightMVP, float4(input.pos, 1.0));
    return output;
}

struct MainUniforms {
    float4x4 viewProj;
    float4x4 model;
    float4x4 lightViewProj;
    float3 cameraPos;
    float3 lightDir;
    float4 color;
    uint shadowMapId;
};
RFX_PUSH_CONSTANTS(MainUniforms, u_Main);

struct MainOutput {
    float4 pos          : SV_Position;
    float3 worldPos     : TEXCOORD0;
    float3 worldNormal  : TEXCOORD1;
    float4 shadowCoord  : TEXCOORD2;
};

[shader("vertex")]
MainOutput vsMain(VertexInput input) {
    MainOutput output;
    float4 worldPos = mul(u_Main.model, float4(input.pos, 1.0));
    output.worldPos = worldPos.xyz;
    output.worldNormal = mul((float3x3)u_Main.model, input.normal);
    output.pos = mul(u_Main.viewProj, worldPos);
    output.shadowCoord = mul(u_Main.lightViewProj, worldPos);
    return output;
}

float CalculateShadow(float4 shadowCoord, uint textureId) {
    float3 projCoords = shadowCoord.xyz / shadowCoord.w;
    float2 uv = projCoords.xy * 0.5 + 0.5;
    uv.y = 1.0 - uv.y;

    float currentDepth = projCoords.z;

    if (currentDepth > 1.0 || uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)
        return 0.0;

    Texture2D shadowMap = GetTexture(textureId);
    SamplerState sam = GetSamplerLinearClamp();

    float shadow = 0.0;
    float2 texelSize = 1.0 / 2048.0;

    for(int x = -1; x <= 1; ++x) {
        for(int y = -1; y <= 1; ++y) {
            float pcfDepth = shadowMap.Sample(sam, uv + float2(x, y) * texelSize).r;
            shadow += (currentDepth - 0.0005 > pcfDepth ? 1.0 : 0.0);
        }
    }
    return shadow / 9.0;
}

[shader("fragment")]
float4 fsMain(MainOutput input) : SV_Target {
    float3 N = normalize(input.worldNormal);
    float3 L = normalize(-u_Main.lightDir);
    float3 V = normalize(u_Main.cameraPos - input.worldPos);
    float3 H = normalize(L + V);

    float3 ambient = 0.15 * u_Main.color.rgb;
    float diff = max(dot(N, L), 0.0);
    float3 diffuse = diff * u_Main.color.rgb;
    float spec = pow(max(dot(N, H), 0.0), 64.0);
    float3 specular = 0.5 * spec * float3(1.0, 1.0, 1.0);

    float shadowVal = CalculateShadow(input.shadowCoord, u_Main.shadowMapId);
    float3 finalColor = ambient + (1.0 - shadowVal) * (diffuse + specular);

    return float4(finalColor, 1.0);
}
)";

#define SHADOW_MAP_SIZE 2048

typedef struct {
    HMM_Vec3 pos;
    HMM_Vec3 normal;
} Vertex;

void AddCube(Vertex* vertices, int* vCount, uint16_t* indices, int* iCount, HMM_Vec3 offset, HMM_Vec3 scale) {
    uint16_t baseIndex = (uint16_t)*vCount;
    HMM_Vec3 nUp = { 0, 1, 0 }, nDown = { 0, -1, 0 }, nLeft = { -1, 0, 0 };
    HMM_Vec3 nRight = { 1, 0, 0 }, nFront = { 0, 0, 1 }, nBack = { 0, 0, -1 };

    struct {
        HMM_Vec3 p;
        HMM_Vec3 n;
    } cubeData[] = {
        { { -1, -1, 1 }, nFront }, { { 1, -1, 1 }, nFront }, { { 1, 1, 1 }, nFront },   { { -1, 1, 1 }, nFront }, { { 1, -1, -1 }, nBack },
        { { -1, -1, -1 }, nBack }, { { -1, 1, -1 }, nBack }, { { 1, 1, -1 }, nBack },   { { -1, 1, 1 }, nUp },    { { 1, 1, 1 }, nUp },
        { { 1, 1, -1 }, nUp },     { { -1, 1, -1 }, nUp },   { { -1, -1, -1 }, nDown }, { { 1, -1, -1 }, nDown }, { { 1, -1, 1 }, nDown },
        { { -1, -1, 1 }, nDown },  { { 1, -1, 1 }, nRight }, { { 1, -1, -1 }, nRight }, { { 1, 1, -1 }, nRight }, { { 1, 1, 1 }, nRight },
        { { -1, -1, -1 }, nLeft }, { { -1, -1, 1 }, nLeft }, { { -1, 1, 1 }, nLeft },   { { -1, 1, -1 }, nLeft },
    };

    for (int i = 0; i < 24; i++) {
        Vertex v;
        v.pos.X = cubeData[i].p.X * scale.X + offset.X;
        v.pos.Y = cubeData[i].p.Y * scale.Y + offset.Y;
        v.pos.Z = cubeData[i].p.Z * scale.Z + offset.Z;
        v.normal = cubeData[i].n;
        vertices[*vCount + i] = v;
    }

    uint16_t faceIndices[] = { 0, 1, 2, 2, 3, 0 };
    for (int f = 0; f < 6; f++) {
        for (int i = 0; i < 6; i++) {
            indices[*iCount + (f * 6) + i] = baseIndex + (f * 4) + faceIndices[i];
        }
    }
    *vCount += 24;
    *iCount += 36;
}

int main(void) {
    if (!rfxOpenWindow("Rafx Shadow Mapping", 1280, 720))
        return 1;

    // geometry
    Vertex vertices[1024];
    uint16_t indices[2048];
    int vCount = 0;
    int iCount = 0;
    AddCube(vertices, &vCount, indices, &iCount, HMM_V3(0, -1.0f, 0), HMM_V3(10.0f, 0.1f, 10.0f));
    AddCube(vertices, &vCount, indices, &iCount, HMM_V3(0, 0.5f, 0), HMM_V3(0.5f, 0.5f, 0.5f));
    AddCube(vertices, &vCount, indices, &iCount, HMM_V3(1.5f, 1.0f, 1.0f), HMM_V3(0.3f, 1.0f, 0.3f));

    RfxBuffer vbo = rfxCreateBuffer(sizeof(Vertex) * vCount, 0, RFX_USAGE_VERTEX_BUFFER, RFX_MEM_GPU_ONLY, vertices);
    RfxBuffer ibo = rfxCreateBuffer(sizeof(uint16_t) * iCount, 0, RFX_USAGE_INDEX_BUFFER, RFX_MEM_GPU_ONLY, indices);

    // resources
    RfxTextureDesc shadowDesc = {};
    shadowDesc.width = SHADOW_MAP_SIZE;
    shadowDesc.height = SHADOW_MAP_SIZE;
    shadowDesc.depth = 1;
    shadowDesc.format = RFX_FORMAT_D32_FLOAT;
    shadowDesc.usage = RFX_TEXTURE_USAGE_DEPTH_STENCIL | RFX_TEXTURE_USAGE_SHADER_RESOURCE;
    RfxTexture shadowMap = rfxCreateTextureEx(&shadowDesc);
    rfxSetTextureName(shadowMap, "ShadowMap");

    // shaders
    RfxShader shader = rfxCompileShaderMem(shaderSource, NULL, 0, NULL, 0);

    RfxVertexLayoutElement mainLayout[] = {
        { 0, RFX_FORMAT_RGB32_FLOAT, offsetof(Vertex, pos), "POSITION" },
        { 1, RFX_FORMAT_RGB32_FLOAT, offsetof(Vertex, normal), "NORMAL" },
    };
    RfxVertexLayoutElement shadowLayout[] = {
        { 0, RFX_FORMAT_RGB32_FLOAT, offsetof(Vertex, pos), "POSITION" },
    };

    // shadow pipeline
    RfxPipelineDesc shadowPsoDesc = {};
    shadowPsoDesc.shader = shader;
    shadowPsoDesc.vsEntryPoint = "vsShadow";
    shadowPsoDesc.vertexLayout = shadowLayout;
    shadowPsoDesc.vertexLayoutCount = 1;
    shadowPsoDesc.vertexStride = sizeof(Vertex);
    shadowPsoDesc.depthFormat = RFX_FORMAT_D32_FLOAT;
    shadowPsoDesc.topology = RFX_TOPOLOGY_TRIANGLE_LIST;
    shadowPsoDesc.cullMode = RFX_CULL_FRONT; // cull front faces to avoid self-shadowing acne
    shadowPsoDesc.depthTest = true;
    shadowPsoDesc.depthWrite = true;
    shadowPsoDesc.attachmentCount = 0;
    shadowPsoDesc.depthBiasConstant = 1.25f;
    shadowPsoDesc.depthBiasClamp = 0.0f;
    shadowPsoDesc.depthBiasSlope = 1.75f;

    RfxPipeline shadowPipeline = rfxCreatePipeline(&shadowPsoDesc);

    // main pipeline
    RfxPipelineDesc mainPsoDesc = {};
    mainPsoDesc.shader = shader;
    mainPsoDesc.vsEntryPoint = "vsMain";
    mainPsoDesc.psEntryPoint = "fsMain";
    mainPsoDesc.vertexLayout = mainLayout;
    mainPsoDesc.vertexLayoutCount = 2;
    mainPsoDesc.vertexStride = sizeof(Vertex);
    mainPsoDesc.colorFormat = rfxGetSwapChainFormat();
    mainPsoDesc.depthFormat = RFX_FORMAT_D32_FLOAT;
    mainPsoDesc.topology = RFX_TOPOLOGY_TRIANGLE_LIST;
    mainPsoDesc.cullMode = RFX_CULL_BACK; // cull back faces (as opposed to front in shadow pipeline)
    mainPsoDesc.depthTest = true;
    mainPsoDesc.depthWrite = true;

    RfxPipeline mainPipeline = rfxCreatePipeline(&mainPsoDesc);

    struct ShadowPush {
        HMM_Mat4 lightMVP;
    } shadowPush;
    struct MainPush {
        HMM_Mat4 viewProj;
        HMM_Mat4 model;
        HMM_Mat4 lightViewProj;
        HMM_Vec3 cameraPos;
        float _pad0;
        HMM_Vec3 lightDir;
        float _pad1;
        RfxColor color;
        uint32_t shadowMapId;
    } mainPush;

    float time = 0.0f;

    while (!rfxWindowShouldClose()) {
        rfxBeginFrame();
        RfxCommandList cmd = rfxGetCommandList();

        time += rfxGetDeltaTime();

        float lightX = sinf(time * 0.5f) * 6.0f;
        float lightZ = cosf(time * 0.5f) * 6.0f;
        HMM_Vec3 lightPos = { lightX, 8.0f, lightZ };
        HMM_Vec3 target = { 0, 0, 0 };
        HMM_Vec3 up = { 0, 1, 0 };

        HMM_Mat4 lightProj = HMM_Orthographic_RH_ZO(-10.0f, 10.0f, -10.0f, 10.0f, 1.0f, 25.0f);
        HMM_Mat4 lightView = HMM_LookAt_RH(lightPos, target, up);
        HMM_Mat4 lightViewProj = HMM_MulM4(lightProj, lightView);

        float aspect = (float)rfxGetWindowWidth() / (float)rfxGetWindowHeight();

        HMM_Mat4 camProj = HMM_Perspective_RH_ZO(HMM_AngleDeg(60.0f), aspect, 0.1f, 100.0f);
        HMM_Vec3 camPos = { 0.0f, 4.0f, 8.0f };
        HMM_Mat4 camView = HMM_LookAt_RH(camPos, target, up);
        HMM_Mat4 camViewProj = HMM_MulM4(camProj, camView);
        HMM_Mat4 model = HMM_M4D(1.0f);

        // shadow pass
        rfxCmdBeginEvent(cmd, "Shadow Pass");
        rfxCmdTransitionTexture(cmd, shadowMap, RFX_STATE_DEPTH_WRITE);
        rfxCmdBeginRenderPass(cmd, NULL, 0, shadowMap, RFX_COLOR(0, 0, 0, 0), 0);
        rfxCmdBindPipeline(cmd, shadowPipeline);

        float shadowViewport[4] = { 0, 0, (float)SHADOW_MAP_SIZE, (float)SHADOW_MAP_SIZE };
        rfxCmdSetViewports(cmd, shadowViewport, 1);
        rfxCmdSetScissor(cmd, 0, 0, SHADOW_MAP_SIZE, SHADOW_MAP_SIZE);

        rfxCmdBindVertexBuffer(cmd, vbo);
        rfxCmdBindIndexBuffer(cmd, ibo, RFX_INDEX_UINT16);

        shadowPush.lightMVP = HMM_MulM4(lightViewProj, model);
        rfxCmdPushConstants(cmd, &shadowPush, sizeof(shadowPush));
        rfxCmdDrawIndexed(cmd, iCount, 1);

        rfxCmdEndRenderPass(cmd);
        rfxCmdEndEvent(cmd);

        // main pass
        rfxCmdBeginEvent(cmd, "Main Pass");
        rfxCmdTransitionTexture(cmd, shadowMap, RFX_STATE_SHADER_READ);
        rfxCmdBeginSwapchainRenderPass(cmd, RFX_FORMAT_D32_FLOAT, RFX_COLOR(25, 25, 30, 255));
        rfxCmdBindPipeline(cmd, mainPipeline);

        float mainViewport[4] = { 0, 0, (float)rfxGetWindowWidth(), (float)rfxGetWindowHeight() };
        rfxCmdSetViewports(cmd, mainViewport, 1);
        rfxCmdSetScissor(cmd, 0, 0, rfxGetWindowWidth(), rfxGetWindowHeight());

        rfxCmdBindVertexBuffer(cmd, vbo);
        rfxCmdBindIndexBuffer(cmd, ibo, RFX_INDEX_UINT16);

        mainPush.viewProj = camViewProj;
        mainPush.model = model;
        mainPush.lightViewProj = lightViewProj;
        mainPush.cameraPos = camPos;
        mainPush.lightDir = HMM_NormV3(HMM_SubV3(target, lightPos));
        mainPush.color = RFX_COLOR(200, 200, 200, 255);
        mainPush.shadowMapId = rfxGetTextureId(shadowMap);

        rfxCmdPushConstants(cmd, &mainPush, sizeof(mainPush));
        rfxCmdDrawIndexed(cmd, iCount, 1);

        rfxCmdEndRenderPass(cmd);
        rfxCmdEndEvent(cmd);

        rfxEndFrame();
    }

    rfxDestroyPipeline(shadowPipeline);
    rfxDestroyPipeline(mainPipeline);
    rfxDestroyShader(shader);
    rfxDestroyTexture(shadowMap);
    rfxDestroyBuffer(vbo);
    rfxDestroyBuffer(ibo);

    return 0;
}
