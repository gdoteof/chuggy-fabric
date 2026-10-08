// The permission model Keto answers from: the object types, the relations a
// tuple may state, and the permits computed from them. `namespaces.location`
// in keto.yaml names this file and the same generated ConfigMap carries both,
// so an edit here rolls the Deployment in ory-keto.yaml.
//
// The import is not resolved at runtime -- Keto's own parser reads this file as
// a model rather than executing it -- and nothing in this tree installs the
// package it names. It is there so an editor can check the shape.
//
// WHO MAY CHANGE WHO HOLDS A ROLE IS HELD HERE AS WELL, as relations of its
// own. Each `*_granters` names who may grant or remove one role,
// `account_creators` who may make an account for a new person, and
// `authority_managers` who may change the holders of these. `Site` is the one
// object above every tenant, and a tenant reaches it by its `site` tuple: a
// tenant without one gets nothing from the site, and no error says so.
//
// A HOLDER IS A PERSON OR THE HOLDERS OF A ROLE, written as a subject set, and
// never the holders of another of these relations. Keto follows such a chain
// and stops at its read depth with an ordinary denial.
//
// KETO ENFORCES NONE OF THE TYPES BELOW. It stores any tuple and follows any
// subject set, so what a holder may be is the access plane's to refuse.
//
// A MODEL THE PARSER REFUSES DOES NOT STOP KETO. It answers ready with no
// namespace at all, and the API and the access plane, which probe every permit
// they name, then never become ready. `POST /opl/syntax/check` on 4469 with
// this file as the body answers `{}` for a model it accepts; it refuses a
// union that begins with `|` and a comma after a call's last argument, both of
// which a formatter writes. The same probe is why a relation or permit comes
// here before the product commit that names it is released, and leaves after.
import { Namespace, Context, SubjectSet } from "@ory/keto-namespace-types"

class User implements Namespace {}

class Site implements Namespace {
  related: {
    admins: User[]
    account_creators: (User | SubjectSet<Site, "admins"> | SubjectSet<Tenant, "admins">)[]
    authority_managers: (User | SubjectSet<Site, "admins">)[]
  }
  permits = {
    administer: (ctx: Context): boolean => this.related.admins.includes(ctx.subject),
    create_account: (ctx: Context): boolean => this.related.account_creators.includes(ctx.subject),
    manage_authorities: (ctx: Context): boolean =>
      this.related.authority_managers.includes(ctx.subject) || this.permits.administer(ctx),
  }
}

class Tenant implements Namespace {
  related: {
    site: Site[]
    admins: User[]
    members: User[]
    hosted_execution: User[]
    admin_granters: (User | SubjectSet<Tenant, "admins"> | SubjectSet<Site, "admins">)[]
    member_granters: (User | SubjectSet<Tenant, "admins"> | SubjectSet<Tenant, "members"> | SubjectSet<Site, "admins">)[]
    hosted_execution_granters: (User | SubjectSet<Tenant, "admins"> | SubjectSet<Site, "admins">)[]
    authority_managers: (User | SubjectSet<Tenant, "admins">)[]
  }
  permits = {
    administer: (ctx: Context): boolean => this.related.admins.includes(ctx.subject),
    invite: (ctx: Context): boolean => this.permits.administer(ctx),
    execute_hosted: (ctx: Context): boolean => this.related.hosted_execution.includes(ctx.subject),
    grant_admin: (ctx: Context): boolean => this.related.admin_granters.includes(ctx.subject),
    grant_member: (ctx: Context): boolean => this.related.member_granters.includes(ctx.subject),
    grant_hosted_execution: (ctx: Context): boolean =>
      this.related.hosted_execution_granters.includes(ctx.subject),
    manage_site_held_authorities: (ctx: Context): boolean =>
      this.related.site.traverse((s) => s.permits.manage_authorities(ctx)),
    manage_authorities: (ctx: Context): boolean =>
      this.related.authority_managers.includes(ctx.subject) ||
      this.related.site.traverse((s) => s.permits.manage_authorities(ctx)),
  }
}

class Project implements Namespace {
  related: {
    tenant: Tenant[]
    admins: User[]
    developers: User[]
    dispatchers: User[]
    agents: User[]
    pools: User[]
    admin_granters: (User | SubjectSet<Project, "admins"> | SubjectSet<Tenant, "admins"> | SubjectSet<Site, "admins">)[]
    developer_granters: (User | SubjectSet<Project, "admins"> | SubjectSet<Project, "developers"> | SubjectSet<Tenant, "admins"> | SubjectSet<Site, "admins">)[]
    dispatcher_granters: (User | SubjectSet<Project, "admins"> | SubjectSet<Tenant, "admins"> | SubjectSet<Site, "admins">)[]
    authority_managers: (User | SubjectSet<Project, "admins"> | SubjectSet<Tenant, "admins">)[]
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
    execute: (ctx: Context): boolean =>
      this.related.pools.includes(ctx.subject) || this.permits.develop(ctx),
    manage_selector: (ctx: Context): boolean => this.permits.administer(ctx),
    grant_admin: (ctx: Context): boolean => this.related.admin_granters.includes(ctx.subject),
    grant_developer: (ctx: Context): boolean => this.related.developer_granters.includes(ctx.subject),
    grant_dispatcher: (ctx: Context): boolean => this.related.dispatcher_granters.includes(ctx.subject),
    manage_authorities: (ctx: Context): boolean =>
      this.related.authority_managers.includes(ctx.subject) ||
      this.related.tenant.traverse((t) => t.permits.manage_authorities(ctx)),
  }
}
