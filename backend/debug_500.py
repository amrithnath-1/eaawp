import os,asyncio,traceback
os.environ['GEMINI_API_KEY']='test'
os.environ['OPENAI_API_KEY']=''
async def main():
    from app.main import app
    from httpx import AsyncClient,ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=True),base_url='http://test') as c:
        r=await c.get('/api/v1/roles/DIGITAL_MARKETING_MANAGER',headers={'X-Tenant-ID':'demo-company-001'})
        print('ROLES:',r.status_code)
        r2=await c.get('/api/v1/integration-manager/integrations',headers={'X-Tenant-ID':'demo-company-001'})
        print('INTEGRATIONS:',r2.status_code)
asyncio.run(main())
