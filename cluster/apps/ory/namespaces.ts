// The permission model Keto answers from: the object types, the relations a
// tuple may state, and the permits computed from them. `namespaces.location`
// in keto.yaml names this file and the same generated ConfigMap carries both,
// so an edit here rolls the Deployment in ory-keto.yaml.
//
// The import is not resolved at runtime -- Keto's own parser reads this file as
// a model rather than executing it -- and nothing in this tree installs the
// package it names. It is there so an editor can check the shape.
import { Namespace, Context } from "@ory/keto-namespace-types"

class User implements Namespace {}

class Tenant implements Namespace {
  related: {
    admins: User[]
    members: User[]
    hosted_execution: User[]
  }
  permits = {
    administer: (ctx: Context): boolean => this.related.admins.includes(ctx.subject),
    invite: (ctx: Context): boolean => this.permits.administer(ctx),
    execute_hosted: (ctx: Context): boolean => this.related.hosted_execution.includes(ctx.subject),
  }
}

class Project implements Namespace {
  related: {
    tenant: Tenant[]
    admins: User[]
    developers: User[]
    dispatchers: User[]
    agents: User[]
  }
  permits = {
    administer: (ctx: Context): boolean =>
      this.related.admins.includes(ctx.subject) ||
      this.related.tenant.traverse((t) => t.permits.administer(ctx)),
    develop: (ctx: Context): boolean =>
      this.related.developers.includes(ctx.subject) || this.permits.administer(ctx),
    read: (ctx: Context): boolean =>
      this.permits.develop(ctx) || this.related.agents.includes(ctx.subject),
    propose: (ctx: Context): boolean => this.permits.develop(ctx),
    dispatch: (ctx: Context): boolean =>
      this.related.dispatchers.includes(ctx.subject) || this.permits.administer(ctx),
    execute: (ctx: Context): boolean => this.permits.develop(ctx),
    manage_selector: (ctx: Context): boolean => this.permits.administer(ctx),
  }
}
