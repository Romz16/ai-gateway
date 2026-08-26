import http from 'k6/http';
import { check } from 'k6';
export const options = {
  stages: [{ duration: '15s', target: 5 }, { duration: '30s', target: 10 }, { duration: '15s', target: 0 }],
  thresholds: { http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<5000'] },
};
export default function () {
  const response = http.post((__ENV.GATEWAY_URL || 'http://localhost:8000') + '/v1/generate',
    JSON.stringify({ task: 'classification', messages: [{role:'user', content:'A great service.'}], cache:true }),
    {headers:{'Content-Type':'application/json','Authorization':'Bearer '+__ENV.GATEWAY_API_KEY}});
  check(response, {'request succeeded': r => r.status === 200});
}
// Provision a dedicated tenant with suitable rate limits before load testing.
// These thresholds are test targets, not measured production guarantees.
