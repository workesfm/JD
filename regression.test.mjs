import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import {parse} from 'acorn'
import {graphql, GraphQLObjectType, GraphQLSchema, GraphQLScalarType, GraphQLString, GraphQLNonNull} from 'graphql'

// Extract the actual field resolver from each source snapshot without loading
// database, wallet, or other unrelated imports. The fallback is GraphQL's own.
function resolverAt (path) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const ast = parse(source, {ecmaVersion: 'latest', sourceType: 'module'})
  const exported = ast.body.find(node => node.type === 'ExportDefaultDeclaration').declaration
  const user = exported.properties.find(property => property.key.name === 'User').value
  const field = user.properties.find(property => property.key.name === 'createdAt')
  return field ? vm.runInNewContext('(' + source.slice(field.value.start, field.value.end) + ')') : undefined
}

const before = resolverAt('./upstream/api/resolvers/user.js')
const after = resolverAt('./candidate/api/resolvers/user.js')
const instant = '2026-01-02T03:04:05.000Z'
const DateScalar = new GraphQLScalarType({name: 'Date', serialize: value => new Date(value).toISOString()})

async function execute (user, resolve) {
  const User = new GraphQLObjectType({name: 'User', fields: {
    name: {type: new GraphQLNonNull(GraphQLString)},
    createdAt: {type: new GraphQLNonNull(DateScalar), resolve}
  }})
  const Item = new GraphQLObjectType({name: 'Item', fields: {user: {type: new GraphQLNonNull(User)}}})
  const Query = new GraphQLObjectType({name: 'Query', fields: {item: {type: Item, resolve: () => ({user})}}})
  return graphql({schema: new GraphQLSchema({query: Query}), source: '{item{user{name createdAt}}}'})
}

test('current resolver nulls the whole item for the real raw-SQL field shape', async () => {
  const result = await execute({name: 'fixture', created_at: instant}, before)
  assert.equal(result.data.item, null)
  assert.equal(result.errors[0].message, 'Cannot return null for non-nullable field User.createdAt.')
})
test('candidate keeps the parent item and returns the raw-SQL creation date', async () => {
  const result = await execute({name: 'fixture', created_at: instant}, after)
  assert.equal(result.errors, undefined)
  assert.equal(result.data.item.user.createdAt, instant)
})
test('candidate preserves Prisma Date values and prioritizes the canonical field', async () => {
  const result = await execute({name: 'fixture', createdAt: new Date(instant), created_at: '2000-01-01T00:00:00Z'}, after)
  assert.equal(result.errors, undefined)
  assert.equal(result.data.item.user.createdAt, instant)
})
test('missing creation dates still fail the non-null contract', async () => {
  const result = await execute({name: 'fixture'}, after)
  assert.equal(result.data.item, null)
  assert.match(result.errors[0].message, /Cannot return null/)
})
