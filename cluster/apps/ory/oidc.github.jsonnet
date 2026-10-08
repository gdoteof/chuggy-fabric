// What a GitHub account becomes when Kratos makes a NEW identity out of one.
// That is registration, and kratos.yaml closes it. Signing in and linking find
// an identity by the account's numeric id and never evaluate this file, so
// nothing written here can fail either of them.
//
// IT READS NOTHING GITHUB SAYS, WHICH IS WHY IT IS THIS SHORT. The identity
// schema requires `email` and this supplies none, so were registration
// reopened, a person arriving from GitHub would be asked for an address rather
// than given an identity under whichever one their account lists. Mapping
// `claims.email` is a decision about whose word an address is taken on, and it
// belongs with the decision to reopen the flow it would serve.
{ identity: { traits: {} } }
