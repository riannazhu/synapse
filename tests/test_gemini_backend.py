import json
import os
import unittest
from unittest.mock import patch
import httpx
from server.config import Settings
from server.jobs.runtime import RetryableError
from server.providers.gemini import Gemini, quote_spans

class GeminiTests(unittest.TestCase):
    def provider(self,handler):
        env=patch.dict(os.environ,{'GEMINI_API_KEY':'fake-key','GEMINI_MODEL':'gemini-2.5-flash'})
        env.start(); self.addCleanup(env.stop)
        return Gemini(Settings('unused','unused','unused'),client=httpx.Client(transport=httpx.MockTransport(handler)),reserve=lambda:None)

    def test_single_structured_call_and_unicode_offsets(self):
        text='🎹 I want to learn piano.'
        def handler(request):
            self.assertEqual(request.headers['x-goog-api-key'],'fake-key')
            self.assertNotIn('fake-key',str(request.url))
            body=json.loads(request.content)
            self.assertIn('responseSchema',body['generationConfig'])
            self.assertEqual(body['generationConfig']['thinkingConfig']['thinkingBudget'],0)
            value={'topics':[{'label':'Piano','kind':'topic','quotes':['learn piano']}],'events':[{'type':'intention','goal_label':'Learn piano','quotes':['I want to learn piano.']}]}
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]})
        result=self.provider(handler).extract(text,[],entry_date="2026-10-17")
        span=result['topics'][0]['evidence_spans'][0]
        self.assertEqual(text[span['start']:span['end']],span['quote'])

    def test_429_honors_retry_after_without_leaking_payload(self):
        p=self.provider(lambda r:httpx.Response(429,headers={'Retry-After':'75'},json={'error':'sensitive provider details'}))
        with self.assertRaises(RetryableError) as raised: p.generate('instruction',{}, {})
        self.assertEqual(raised.exception.retry_after,75)
        self.assertNotIn('sensitive',str(raised.exception))

    def test_ambiguous_quote_is_rejected(self):
        with self.assertRaises(ValueError): quote_spans(['piano'],'piano and piano')

    def test_schema_repair_is_bounded(self):
        count=0
        def handler(request):
            nonlocal count
            count+=1
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"topics":[],"events":"wrong"}'}]}}]})
        with self.assertRaises(ValueError): self.provider(handler).extract('Journal.',[],entry_date='2026-10-17')
        self.assertEqual(count,2)
