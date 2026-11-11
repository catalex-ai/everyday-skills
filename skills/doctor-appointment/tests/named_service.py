"""Test helper: a Service whose patients already gave their name.

A patient cannot book until the patient has a stored name (NAME_REQUIRED), so
suites that are about something else build their patient sessions with this
Service. Name-gating tests use core.Service directly.
"""
import core

class Service(core.Service):
    def __init__(self,identity,*args,**kwargs):
        super().__init__(identity,*args,**kwargs)
        if identity.role=='patient':self.name_patient()
    def name_patient(self):
        if not self.patients.get(self.identity.subject).get('name'):self.patients.set_name(self.identity.subject,'Test '+self.identity.subject)
